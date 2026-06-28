function setStatus(text) {
    document.getElementById("status").innerText = text;
}

function setBar(id, value, max) {
    let pct = 0;
    if (typeof value === "number") {
        pct = Math.max(0, Math.min(100, (value / max) * 100));
    }
    document.getElementById(id).style.width = pct + "%";
}

function markActive(id) {
    document.querySelectorAll(".grid button").forEach(b => b.classList.remove("active"));
    const btn = document.getElementById("station-" + id);
    if (btn) btn.classList.add("active");
}

function reloadPlayer() {
    const audio = document.getElementById("player");
    const source = audio.querySelector("source");
    
    const baseUrl = source.dataset.base || source.getAttribute("src").split("?")[0];
    source.dataset.base = baseUrl;
    source.src = baseUrl + "?t=" + Date.now();

    audio.load();
    audio.play().catch(() => {});
}

async function playStation(id) {
    setStatus("Starte Sender...");
    try {
        const res = await fetch("/api/play/" + id, {method: "POST"});
        const data = await res.json();

        if (!data.ok) {
            setStatus("Fehler: " + (data.error || "unbekannt"));
            return;
        }

        document.getElementById("now").innerText = data.station.label;

        const logo = document.getElementById("stationLogo");
        const fallback = document.getElementById("logoFallback");
        logo.src = data.logo + "?t=" + Date.now();
        logo.style.display = "block";
        fallback.style.display = "none";
        logo.onerror = function() {
            logo.style.display = "none";
            fallback.style.display = "block";
        };

        markActive(id);
        reloadPlayer();
        setStatus("Läuft.");
        setTimeout(refreshStatus, 1500);
    } catch (e) {
        setStatus("Fehler: " + e);
    }
}

async function stopRadio() {
    setStatus("Stoppe...");
    await fetch("/api/stop", {method: "POST"});
    document.getElementById("now").innerText = "Noch kein Sender gewählt";
    document.getElementById("radiotext").innerText = "Radiotext erscheint hier.";
    document.querySelectorAll(".grid button").forEach(b => b.classList.remove("active"));
    setStatus("Gestoppt.");
}

async function refreshStatus() {
    try {
        const res = await fetch("/api/status?t=" + Date.now());
        const data = await res.json();

        const meta = data.metadata || {};
        const dig = meta.digrad_status || {};
        const ens = meta.ensemble_info || {};

        if (data.current && data.current.label) {
            document.getElementById("now").innerText = data.current.label;
        }

        document.getElementById("radiotext").innerText =
            meta.station_text || "Kein Radiotext empfangen.";

        document.getElementById("ensemble").innerText =
            "Ensemble: " + (ens.label || "—");

        document.getElementById("freq").innerText =
            "Frequenz: " + (dig.tune_freq ? dig.tune_freq + " kHz" : "—");

        document.getElementById("valid").innerText =
            "Signal: " + (dig.valid === 1 ? "gültig" : "—");

        document.getElementById("rssiText").innerText =
            dig.rssi !== undefined ? dig.rssi : "—";
        document.getElementById("snrText").innerText =
            dig.snr !== undefined ? dig.snr + " dB" : "—";
        document.getElementById("ficText").innerText =
            dig.FIC_quality !== undefined ? dig.FIC_quality + "%" : "—";

        setBar("rssiBar", dig.rssi, 80);
        setBar("snrBar", dig.snr, 20);
        setBar("ficBar", dig.FIC_quality, 100);

        setStatus(data.stream_status && data.stream_status.running ? "Stream läuft." : "Bereit.");
    } catch (e) {
        setStatus("Statusfehler: " + e);
    }
}

setInterval(refreshStatus, 5000);
refreshStatus();
