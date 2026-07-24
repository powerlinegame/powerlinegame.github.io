const flows = {

    crime: [
        "Disturbance Type",
        "Situation",
        "Location",
        "In Progress?",
        "Weapons?",
        "Suspect Description",
        "Vehicle",
        "Direction of Travel",
        "Additional Information"
    ],

    medical: [
        "Situation",
        "Location",
        "Patient Conscious?",
        "Breathing?",
        "Age",
        "Primary Complaint",
        "Additional Information"
    ],

    fire: [
        "Disturbance Type",
        "Situation",
        "Location",
        "People Trapped?",
        "Hazards",
        "Additional Information"
    ]

};

const incidentLabels = {
    crime: "crime emergency",
    medical: "medical emergency",
    fire: "fire emergency"
};

let calls = [];
let active = null;

const content = document.getElementById("content");
const startScreen = document.getElementById("start");
const tabs = document.getElementById("tabs");
const questionEl = document.getElementById("question");
const input = document.getElementById("input");
const log = document.getElementById("log");
const progressBar = document.getElementById("progressBar");
const clockEl = document.getElementById("clock");
const transmitArea = document.getElementById("transmitArea");
const transmitBtn = document.getElementById("transmitBtn");
const statusEl = document.getElementById("status");
const replay = document.getElementById("replay");

function createCall(type) {
    startScreen.style.display = "none";

    const call = {
        id: calls.length + 1,
        type: type,
        step: 0,
        answers: {},
        timer: 0,
        complete: false,
        transmitted: false
    };

    calls.push(call);
    active = call;

    drawTabs();
    content.classList.remove("hidden");
    transmitArea.classList.add("hidden");
    statusEl.textContent = "";
    statusEl.className = "status";
    replay.hidden = true;
    input.disabled = false;

    showQuestion();
}

function newCall() {
    active = null;
    startScreen.style.display = "block";
    content.classList.add("hidden");
    clockEl.textContent = "CALL 00:00";
}

function drawTabs() {
    tabs.innerHTML = "<button onclick='newCall()'>+</button>";

    calls.forEach((call) => {
        const b = document.createElement("button");
        b.className = "tab" + (active === call ? " active" : "");
        b.innerHTML = "Call " + call.id + (call.complete ? " ✓" : "");
        b.onclick = () => {
            active = call;
            drawTabs();
            showQuestion();
        };
        tabs.appendChild(b);
    });
}

function showQuestion() {
    if (!active) {
        return;
    }

    if (active.complete) {
        questionEl.innerText = "Dispatch Complete";
        input.value = "";
        input.disabled = true;
        transmitArea.classList.remove("hidden");
    } else {
        questionEl.innerText = flows[active.type][active.step];
        input.value = "";
        input.disabled = false;
        transmitArea.classList.add("hidden");
    }

    updateLog();
    updateProgress();
    updateClock();
    input.focus();
}

function finishCall() {
    active.complete = true;
    active.step = flows[active.type].length;
    drawTabs();
    showQuestion();
    transmitDispatch(active);
}

function setStatus(message, type = "") {
    statusEl.textContent = message;
    statusEl.className = "status" + (type ? " " + type : "");
}

async function transmitDispatch(call = active) {
    if (!call || !call.complete) {
        return;
    }

    transmitBtn.disabled = true;
    setStatus("Synthesizing dispatch message...", "busy");

    try {
        const response = await fetch("/api/dispatch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                incident_type: call.type,
                answers: call.answers
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Transmission failed");
        }

        call.transmitted = true;

        let msg = `Playing ${data.duration_sec.toFixed(1)}s dispatch.`;
        if (data.radio_connected) {
            msg += ` Radio channel ${data.radio_channel} active.`;
        } else {
            msg += " Speakers only (no radio device configured).";
        }

        setStatus(msg, "ok");

        if (data.wav) {
            replay.src = data.wav + "?t=" + Date.now();
            replay.hidden = false;
        }
    } catch (err) {
        setStatus(err.message, "error");
    } finally {
        transmitBtn.disabled = false;
    }
}

input.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !active || active.complete) {
        return;
    }

    const question = flows[active.type][active.step];
    active.answers[question] = this.value;
    active.step++;

    if (active.step >= flows[active.type].length) {
        finishCall();
        return;
    }

    showQuestion();
});

transmitBtn.addEventListener("click", () => transmitDispatch(active));

function updateLog() {
    if (!active) {
        log.innerText = "No information entered.";
        return;
    }

    let text = "Incident: " + incidentLabels[active.type] + "\n\n";

    for (const item in active.answers) {
        text += item + ": " + active.answers[item] + "\n";
    }

    log.innerText = text.trim() || "No information entered.";
}

function updateProgress() {
    if (!active) {
        progressBar.style.width = "0%";
        return;
    }

    const total = flows[active.type].length;
    const percent = (active.step / total) * 100;
    progressBar.style.width = percent + "%";
}

function updateClock() {
    if (!active) {
        clockEl.textContent = "CALL 00:00";
        return;
    }

    const mins = String(Math.floor(active.timer / 60)).padStart(2, "0");
    const secs = String(active.timer % 60).padStart(2, "0");
    clockEl.textContent = "CALL " + mins + ":" + secs;
}

setInterval(() => {
    calls.forEach((c) => {
        c.timer++;
    });
    updateClock();
}, 1000);

fetch("/api/health")
    .then((r) => r.json())
    .then((data) => {
        if (!data.clips_found) {
            console.warn("No clips found in clips/ — TTS will use espeak fallback only.");
        }
    })
    .catch(() => {
        console.warn("TTS server not reachable — start server.py first.");
    });
