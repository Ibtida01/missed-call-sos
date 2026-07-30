import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws";

// ngrok free tunnels show an HTML warning page to browser requests unless
// this header is present - without it, fetch gets a 200 OK with no CORS
// headers, which the browser reports as a CORS error even though the
// request "succeeded". Harmless to send this even against Vercel/Render.
const API_HEADERS = { "ngrok-skip-browser-warning": "true" };

const LINES = [
  { level: 3, key: "sev-3", en: "Need rescue", bn: "উদ্ধার দরকার", calls: "call 3 times" },
  { level: 2, key: "sev-2", en: "Evacuating", bn: "সরে যাচ্ছি", calls: "call 2 times" },
  { level: 1, key: "sev-1", en: "Water rising", bn: "পানি বাড়ছে", calls: "call once" },
];

function timeAgo(iso) {
  const secs = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h`;
}

function clockUTC() {
  return new Date().toISOString().slice(11, 19);
}

export default function App() {
  const [calls, setCalls] = useState([]);
  const [stats, setStats] = useState({ total: 0, by_severity: {}, places: 0, callers: 0 });
  const [singleNumber, setSingleNumber] = useState("not configured");
  const [repeatWindow, setRepeatWindow] = useState(90);
  const [link, setLink] = useState("connecting");
  const [flare, setFlare] = useState(null);
  const [now, setNow] = useState(clockUTC());

  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const markersRef = useRef(new Map());
  const flareTimer = useRef(null);

  /* ---------------------------------------------------------------- map */
  useEffect(() => {
    const map = L.map("map", {
      center: [23.75, 90.4],
      zoom: 7,
      zoomControl: false,
      attributionControl: true,
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
      {
        attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
        maxZoom: 18,
      }
    ).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => map.remove();
  }, []);

  const addMarker = useCallback((call) => {
    if (!layerRef.current || markersRef.current.has(call.id)) return;
    const icon = L.divIcon({
      className: "pin-wrap",
      html: `<span class="pin pin-${call.severity}"><i class="pin-ring"></i><i class="pin-dot"></i></span>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
    const marker = L.marker([call.lat, call.lng], { icon }).addTo(layerRef.current);
    marker.bindTooltip(
      `<b>${call.label.en}</b><br/>${call.upazila}, ${call.district}<br/>` +
        `<span class="tt-dim">${call.caller_masked} · ${
          call.registered ? "registered" : "unregistered"
        }</span>`,
      { direction: "top", offset: [0, -10], className: "tt" }
    );
    markersRef.current.set(call.id, marker);
  }, []);

  /* ------------------------------------------------------------ initial */
  useEffect(() => {
    fetch(`${API_BASE}/api/calls`, { headers: API_HEADERS })
      .then((r) => r.json())
      .then((d) => {
        setCalls(d.calls);
        setStats(d.stats);
        setSingleNumber(d.config?.single_number || "not configured");
        setRepeatWindow(d.config?.repeat_window_seconds || 90);
        d.calls.forEach(addMarker);
      })
      .catch(() => setLink("offline"));
  }, [addMarker]);

  /* ---------------------------------------------------------- websocket */
  useEffect(() => {
    let ws;
    let retry;
    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => setLink("live");
      ws.onclose = () => {
        setLink("offline");
        retry = setTimeout(connect, 2500);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.stats) setStats(msg.stats);
        if (msg.type === "call") {
          setCalls((prev) => [msg.call, ...prev].slice(0, 300));
          addMarker(msg.call);
          setFlare(msg.call.severity);
          clearTimeout(flareTimer.current);
          flareTimer.current = setTimeout(() => setFlare(null), 1100);
        }
        if (msg.type === "reset") {
          setCalls([]);
          layerRef.current?.clearLayers();
          markersRef.current.clear();
        }
      };
    };
    connect();
    return () => {
      clearTimeout(retry);
      ws && ws.close();
    };
  }, [addMarker]);

  /* -------------------------------------------------------------- clock */
  useEffect(() => {
    const t = setInterval(() => setNow(clockUTC()), 1000);
    return () => clearInterval(t);
  }, []);

  const simulate = (severity) =>
    fetch(`${API_BASE}/api/simulate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...API_HEADERS },
      body: JSON.stringify({ severity }),
    }).catch(() => {});

  const reset = () =>
    fetch(`${API_BASE}/api/calls`, { method: "DELETE", headers: API_HEADERS }).catch(() => {});

  const rescues = Number(stats.by_severity?.["3"] || 0);
  const lastPerLine = useMemo(() => {
    const m = {};
    for (const c of calls) if (!(c.severity in m)) m[c.severity] = c;
    return m;
  }, [calls]);

  return (
    <div className={`console ${flare ? `flare flare-${flare}` : ""}`}>
      <header className="bar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">Missed Call SOS</span>
          <span className="brand-sub">flood telemetry over unanswered calls</span>
        </div>
        <div className="bar-right">
          <span className="clock">{now} UTC</span>
          <span className={`link link-${link}`}>{link}</span>
        </div>
      </header>

      <main className="grid">
        {/* ------------------------------------------------ switchboard */}
        <section className="panel board">
          <h2 className="panel-title">One number, three calls</h2>
          <div className="single-number">{singleNumber}</div>
          <p className="single-number-note">
            Call once for level 1. Call again within {repeatWindow}s to escalate.
            Same number, no menu, no app.
          </p>
          <div className="lines">
            {LINES.map((line) => {
              const count = Number(stats.by_severity?.[line.level] || 0);
              const last = lastPerLine[line.level];
              return (
                <div
                  key={line.level}
                  className={`line ${line.key} ${flare === line.level ? "ringing" : ""}`}
                >
                  <span className="lamp" aria-hidden="true" />
                  <div className="line-text">
                    <span className="line-en">{line.en}</span>
                    <span className="line-bn">{line.bn}</span>
                    <span className="line-num">{line.calls}</span>
                  </div>
                  <div className="line-count">
                    <b>{count}</b>
                    <span>{last ? timeAgo(last.created_at) + " ago" : "—"}</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="readout">
            <div>
              <b>{stats.total}</b>
              <span>calls</span>
            </div>
            <div>
              <b>{stats.callers}</b>
              <span>phones</span>
            </div>
            <div>
              <b>{stats.places}</b>
              <span>upazilas</span>
            </div>
            <div className={rescues > 0 ? "urgent" : ""}>
              <b>{rescues}</b>
              <span>rescues</span>
            </div>
          </div>

          <div className="controls">
            <span className="controls-label">Test the console</span>
            <div className="controls-row">
              {LINES.map((l) => (
                <button key={l.level} className={`btn ${l.key}`} onClick={() => simulate(l.level)}>
                  Ring line {l.level}
                </button>
              ))}
            </div>
            <button className="btn btn-ghost" onClick={reset}>
              Clear the board
            </button>
          </div>
        </section>

        {/* -------------------------------------------------------- map */}
        <section className="panel map-panel">
          <div id="map" />
          <div className="legend">
            {LINES.map((l) => (
              <span key={l.level} className={`legend-item ${l.key}`}>
                <i /> {l.en}
              </span>
            ))}
          </div>
        </section>

        {/* -------------------------------------------------------- log */}
        <section className="panel log">
          <h2 className="panel-title">
            Incoming <span className="panel-note">newest first</span>
          </h2>
          {calls.length === 0 ? (
            <p className="empty">
              No calls yet. Ring a line from the test controls, or dial one of the numbers
              above from any phone.
            </p>
          ) : (
            <ul className="log-list">
              {calls.slice(0, 60).map((c) => (
                <li key={c.id} className={`log-row sev-${c.severity}`}>
                  <span className="log-lamp" aria-hidden="true" />
                  <span className="log-place">
                    {c.upazila}
                    <small>{c.district}</small>
                  </span>
                  <span className="log-what">
                    {c.label.en}
                    <small className="bn">{c.label.bn}</small>
                  </span>
                  <span className="log-meta">
                    {c.caller_masked}
                    <small>
                      {c.registered ? "registered" : "unregistered"}
                      {c.source === "simulated" ? " · test" : ""}
                      {c.source === "mobile" ? " · live call" : ""}
                    </small>
                  </span>
                  <span className="log-age">{timeAgo(c.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </main>

      <footer className="foot">
        Calls are rejected, never answered — the caller is not charged. Numbers are masked on
        screen; unregistered callers are placed approximately and labelled as such.
      </footer>
    </div>
  );
}