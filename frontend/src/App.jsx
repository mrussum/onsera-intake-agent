import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Risk colour palette
// ---------------------------------------------------------------------------
const RISK_COLORS = {
  critical: { bg: "#fff0f0", border: "#e53935", badge: "#e53935", text: "#fff" },
  high:     { bg: "#fff8e1", border: "#fb8c00", badge: "#fb8c00", text: "#fff" },
  medium:   { bg: "#fffde7", border: "#fdd835", badge: "#f9a825", text: "#333" },
  low:      { bg: "#f1f8e9", border: "#66bb6a", badge: "#43a047", text: "#fff" },
};

function riskColors(level) {
  return RISK_COLORS[level?.toLowerCase()] || RISK_COLORS.low;
}

// ---------------------------------------------------------------------------
// Styles (inline only — no external UI libraries)
// ---------------------------------------------------------------------------
const S = {
  app: {
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    background: "#f5f7fa",
    minHeight: "100vh",
    color: "#1a1a2e",
  },
  header: {
    background: "linear-gradient(135deg, #1a237e 0%, #283593 100%)",
    color: "#fff",
    padding: "20px 32px",
    boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
    display: "flex",
    alignItems: "center",
    gap: 16,
  },
  headerTitle: { margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: 0.5 },
  headerSub: { margin: 0, fontSize: 13, opacity: 0.75, marginTop: 2 },
  main: { maxWidth: 1100, margin: "0 auto", padding: "28px 24px" },
  card: {
    background: "#fff",
    borderRadius: 12,
    boxShadow: "0 1px 6px rgba(0,0,0,0.08)",
    padding: 24,
    marginBottom: 24,
  },
  sectionTitle: { fontSize: 16, fontWeight: 700, marginBottom: 16, color: "#1a237e" },
  row: { display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" },
  input: {
    padding: "10px 14px",
    border: "1.5px solid #c5cae9",
    borderRadius: 8,
    fontSize: 14,
    outline: "none",
    width: 220,
  },
  btn: (color) => ({
    padding: "10px 20px",
    background: color,
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    fontSize: 14,
    fontWeight: 600,
    transition: "opacity 0.15s",
  }),
  btnDisabled: {
    padding: "10px 20px",
    background: "#bdbdbd",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "not-allowed",
    fontSize: 14,
    fontWeight: 600,
  },
  recordingDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    background: "#e53935",
    display: "inline-block",
    marginRight: 6,
    animation: "pulse 1s infinite",
  },
  statusBox: {
    marginTop: 14,
    padding: "12px 16px",
    borderRadius: 8,
    background: "#e8eaf6",
    fontSize: 13,
    color: "#283593",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
    gap: 18,
  },
  intakeCard: (level) => ({
    background: riskColors(level).bg,
    border: `2px solid ${riskColors(level).border}`,
    borderRadius: 12,
    padding: 18,
    cursor: "pointer",
    transition: "transform 0.15s, box-shadow 0.15s",
    position: "relative",
  }),
  badge: (level) => ({
    display: "inline-block",
    background: riskColors(level).badge,
    color: riskColors(level).text,
    fontSize: 11,
    fontWeight: 700,
    padding: "3px 10px",
    borderRadius: 20,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  }),
  reviewBanner: {
    background: "#e53935",
    color: "#fff",
    fontSize: 12,
    fontWeight: 700,
    padding: "5px 12px",
    borderRadius: 6,
    marginBottom: 10,
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
  modalOverlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.55)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  modal: {
    background: "#fff",
    borderRadius: 14,
    maxWidth: 780,
    width: "92vw",
    maxHeight: "88vh",
    overflowY: "auto",
    padding: 32,
    boxShadow: "0 8px 40px rgba(0,0,0,0.25)",
    position: "relative",
  },
  closeBtn: {
    position: "absolute",
    top: 16,
    right: 16,
    background: "none",
    border: "none",
    fontSize: 22,
    cursor: "pointer",
    color: "#666",
  },
  pre: {
    background: "#f5f5f5",
    borderRadius: 8,
    padding: 14,
    fontSize: 12,
    overflowX: "auto",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  latencyRow: { display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 },
  latencyChip: {
    background: "#e8eaf6",
    borderRadius: 6,
    padding: "4px 10px",
    fontSize: 12,
    color: "#3949ab",
  },
};

// ---------------------------------------------------------------------------
// Detail Modal
// ---------------------------------------------------------------------------
function DetailModal({ intake, onClose }) {
  if (!intake) return null;
  const level = intake.risk_level || "low";
  const colors = riskColors(level);

  return (
    <div style={S.modalOverlay} onClick={onClose}>
      <div style={S.modal} onClick={(e) => e.stopPropagation()}>
        <button style={S.closeBtn} onClick={onClose}>✕</button>
        <div style={{ marginBottom: 18 }}>
          <span style={S.badge(level)}>{level}</span>
          {intake.requires_human_review && (
            <span style={{ ...S.reviewBanner, display: "inline-flex", marginLeft: 10 }}>
              ⚠ Review Required
            </span>
          )}
        </div>

        <h2 style={{ margin: "0 0 4px", fontSize: 18 }}>
          Patient: {intake.patient_id}
        </h2>
        <div style={{ fontSize: 12, color: "#888", marginBottom: 20 }}>
          {intake.completed_at ? new Date(intake.completed_at).toLocaleString() : ""}
          {intake.total_ms ? ` · Total: ${intake.total_ms}ms` : ""}
        </div>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8 }}>
          Clinical Summary
        </h3>
        <div
          style={{
            background: colors.bg,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: 16,
            fontSize: 13,
            lineHeight: 1.7,
            whiteSpace: "pre-wrap",
            marginBottom: 20,
          }}
        >
          {intake.clinical_summary || "No summary available."}
        </div>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8 }}>
          Clinical Signals
        </h3>
        <pre style={S.pre}>
          {JSON.stringify(intake.clinical_signals, null, 2)}
        </pre>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>
          Meal / Nutritional Data
        </h3>
        <pre style={S.pre}>
          {JSON.stringify(intake.meal_data, null, 2)}
        </pre>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>
          Node Latency Breakdown
        </h3>
        <div style={S.latencyRow}>
          {Object.entries(intake.latency_ms || {}).map(([node, ms]) => (
            <span key={node} style={S.latencyChip}>
              {node}: {ms}ms
            </span>
          ))}
        </div>

        {intake.risk_reasons?.length > 0 && (
          <>
            <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>
              Risk Reasons
            </h3>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
              {intake.risk_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Intake Card
// ---------------------------------------------------------------------------
function IntakeCard({ intake, onClick }) {
  const level = intake.risk_level || "low";
  return (
    <div
      style={S.intakeCard(level)}
      onClick={() => onClick(intake)}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-2px)";
        e.currentTarget.style.boxShadow = "0 6px 20px rgba(0,0,0,0.12)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "";
        e.currentTarget.style.boxShadow = "";
      }}
    >
      {intake.requires_human_review && (
        <div style={S.reviewBanner}>⚠ Review Required</div>
      )}
      <div style={S.row}>
        <span style={S.badge(level)}>{level}</span>
        <strong style={{ fontSize: 14 }}>{intake.patient_id}</strong>
      </div>
      <div style={{ fontSize: 11, color: "#888", margin: "6px 0 10px" }}>
        {intake.completed_at ? new Date(intake.completed_at).toLocaleString() : ""}
      </div>
      <p style={{ fontSize: 12, margin: 0, color: "#444", lineHeight: 1.5 }}>
        {intake.summary_preview
          ? intake.summary_preview.substring(0, 160) + (intake.summary_preview.length > 160 ? "…" : "")
          : "No summary available."}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Voice Recorder
// ---------------------------------------------------------------------------
function VoiceRecorder({ onSubmit }) {
  const [patientId, setPatientId] = useState("");
  const [recording, setRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [pollStatus, setPollStatus] = useState(null);
  const mediaRecorder = useRef(null);
  const chunks = useRef([]);
  const pollInterval = useRef(null);

  const startRecording = useCallback(async () => {
    chunks.current = [];
    setAudioBlob(null);
    setAudioUrl(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder.current = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRecorder.current.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.current.push(e.data);
      };
      mediaRecorder.current.onstop = () => {
        const blob = new Blob(chunks.current, { type: "audio/webm" });
        setAudioBlob(blob);
        setAudioUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach((t) => t.stop());
      };
      mediaRecorder.current.start();
      setRecording(true);
    } catch (err) {
      alert("Microphone access denied: " + err.message);
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorder.current && recording) {
      mediaRecorder.current.stop();
      setRecording(false);
    }
  }, [recording]);

  const submitRecording = useCallback(async () => {
    if (!audioBlob || !patientId.trim()) {
      alert("Please enter a patient ID and record audio first.");
      return;
    }
    setSubmitting(true);
    setPollStatus("Uploading…");

    const form = new FormData();
    form.append("audio", audioBlob, "intake.webm");
    form.append("patient_id", patientId.trim());

    try {
      const res = await fetch(`${API_BASE}/intake`, { method: "POST", body: form });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      setPollStatus("Processing…");

      // Poll every 2 seconds
      pollInterval.current = setInterval(async () => {
        const r = await fetch(`${API_BASE}/intake/${data.job_id}`);
        const job = await r.json();
        if (job.status === "complete") {
          clearInterval(pollInterval.current);
          setPollStatus("Complete ✓");
          setSubmitting(false);
          onSubmit(); // refresh dashboard
        } else if (job.status === "error") {
          clearInterval(pollInterval.current);
          setPollStatus("Error: " + (job.error || "Unknown error"));
          setSubmitting(false);
        } else {
          setPollStatus(`Processing… (${Object.keys(job.latency_ms || {}).join(", ") || "starting"})`);
        }
      }, 2000);
    } catch (err) {
      setPollStatus("Error: " + err.message);
      setSubmitting(false);
    }
  }, [audioBlob, patientId, onSubmit]);

  return (
    <div style={S.card}>
      <div style={S.sectionTitle}>Submit Patient Voice Check-In</div>
      <div style={S.row}>
        <input
          style={S.input}
          placeholder="Patient ID (e.g. P1001)"
          value={patientId}
          onChange={(e) => setPatientId(e.target.value)}
          disabled={submitting}
        />
        {!recording ? (
          <button
            style={audioBlob ? S.btn("#757575") : S.btn("#1565c0")}
            onClick={startRecording}
            disabled={submitting}
          >
            {audioBlob ? "Re-record" : "🎤 Start Recording"}
          </button>
        ) : (
          <button style={S.btn("#e53935")} onClick={stopRecording}>
            <span style={S.recordingDot} />
            Stop Recording
          </button>
        )}
        <button
          style={audioBlob && patientId && !submitting ? S.btn("#2e7d32") : S.btnDisabled}
          onClick={submitRecording}
          disabled={!audioBlob || !patientId || submitting}
        >
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </div>

      {audioUrl && (
        <div style={{ marginTop: 14 }}>
          <audio controls src={audioUrl} style={{ height: 36 }} />
        </div>
      )}

      {pollStatus && (
        <div style={S.statusBox}>
          {jobId && <span style={{ color: "#666", fontSize: 11 }}>Job: {jobId} · </span>}
          {pollStatus}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
function Dashboard({ intakes, loading }) {
  if (loading && intakes.length === 0) {
    return (
      <div style={S.card}>
        <div style={{ color: "#888", fontSize: 14 }}>Loading dashboard…</div>
      </div>
    );
  }

  if (intakes.length === 0) {
    return (
      <div style={S.card}>
        <div style={{ color: "#888", fontSize: 14 }}>
          No completed intakes yet. Submit a voice check-in above.
        </div>
      </div>
    );
  }

  return (
    <div style={S.grid}>
      {intakes.map((intake) => (
        <IntakeCard key={intake.job_id} intake={intake} onClick={() => {}} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// App (root)
// ---------------------------------------------------------------------------
export default function App() {
  const [intakes, setIntakes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedIntake, setSelectedIntake] = useState(null);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/dashboard`);
      if (res.ok) setIntakes(await res.json());
    } catch (_) {
      // silently ignore network errors during polling
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll dashboard every 10 seconds
  useEffect(() => {
    fetchDashboard();
    const id = setInterval(fetchDashboard, 10000);
    return () => clearInterval(id);
  }, [fetchDashboard]);

  return (
    <div style={S.app}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        * { box-sizing: border-box; }
        body { margin: 0; }
      `}</style>

      <header style={S.header}>
        <div>
          <h1 style={S.headerTitle}>Onsera Health · Intake Agent</h1>
          <p style={S.headerSub}>Clinician Dashboard — AI-Powered Patient Check-In System</p>
        </div>
        <div style={{ marginLeft: "auto", fontSize: 13, opacity: 0.8 }}>
          {intakes.length} intake{intakes.length !== 1 ? "s" : ""} on record
        </div>
      </header>

      <main style={S.main}>
        <VoiceRecorder onSubmit={fetchDashboard} />

        <div style={{ ...S.card, marginBottom: 0 }}>
          <div style={{ ...S.sectionTitle, marginBottom: 18 }}>
            Recent Intakes
            <span style={{ fontSize: 12, fontWeight: 400, color: "#888", marginLeft: 10 }}>
              sorted by risk · refreshes every 10s
            </span>
          </div>
          <div style={S.grid}>
            {intakes.length === 0 && !loading && (
              <div style={{ color: "#888", fontSize: 14 }}>
                No completed intakes yet. Submit a voice check-in above.
              </div>
            )}
            {intakes.map((intake) => (
              <IntakeCard
                key={intake.job_id}
                intake={intake}
                onClick={setSelectedIntake}
              />
            ))}
          </div>
          {loading && intakes.length > 0 && (
            <div style={{ fontSize: 12, color: "#aaa", marginTop: 14 }}>Refreshing…</div>
          )}
        </div>
      </main>

      {selectedIntake && (
        <DetailModal
          intake={selectedIntake}
          onClose={() => setSelectedIntake(null)}
        />
      )}
    </div>
  );
}
