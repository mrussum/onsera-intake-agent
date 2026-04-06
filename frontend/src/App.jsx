import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const API_KEY  = import.meta.env.VITE_API_KEY  || "";

/** Returns headers with X-API-Key injected (if a key is configured). */
function apiHeaders(extra = {}) {
  return API_KEY ? { "X-API-Key": API_KEY, ...extra } : extra;
}

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
// Inline styles
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
  headerSub:   { margin: 0, fontSize: 13, opacity: 0.75, marginTop: 2 },
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
  textarea: {
    padding: "10px 14px",
    border: "1.5px solid #c5cae9",
    borderRadius: 8,
    fontSize: 13,
    width: "100%",
    resize: "vertical",
    fontFamily: "inherit",
    minHeight: 72,
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
    width: 10, height: 10, borderRadius: "50%",
    background: "#e53935", display: "inline-block",
    marginRight: 6, animation: "pulse 1s infinite",
  },
  statusBox: {
    marginTop: 14, padding: "12px 16px", borderRadius: 8,
    background: "#e8eaf6", fontSize: 13, color: "#283593",
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
    fontSize: 11, fontWeight: 700, padding: "3px 10px",
    borderRadius: 20, textTransform: "uppercase", letterSpacing: 0.8,
  }),
  reviewBanner: {
    background: "#e53935", color: "#fff",
    fontSize: 12, fontWeight: 700,
    padding: "5px 12px", borderRadius: 6,
    marginBottom: 10, display: "flex", alignItems: "center", gap: 6,
  },
  waitingBanner: {
    background: "#f57c00", color: "#fff",
    fontSize: 12, fontWeight: 700,
    padding: "5px 12px", borderRadius: 6,
    marginBottom: 10, display: "flex", alignItems: "center", gap: 6,
  },
  modalOverlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
  },
  modal: {
    background: "#fff", borderRadius: 14,
    maxWidth: 820, width: "92vw", maxHeight: "90vh",
    overflowY: "auto", padding: 32,
    boxShadow: "0 8px 40px rgba(0,0,0,0.25)", position: "relative",
  },
  closeBtn: {
    position: "absolute", top: 16, right: 16,
    background: "none", border: "none", fontSize: 22,
    cursor: "pointer", color: "#666",
  },
  pre: {
    background: "#f5f5f5", borderRadius: 8, padding: 14,
    fontSize: 12, overflowX: "auto", whiteSpace: "pre-wrap", wordBreak: "break-word",
  },
  latencyRow: { display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 },
  latencyChip: {
    background: "#e8eaf6", borderRadius: 6, padding: "4px 10px",
    fontSize: 12, color: "#3949ab",
  },
  divider: { borderTop: "1px solid #e0e0e0", margin: "20px 0" },
};


// ---------------------------------------------------------------------------
// Approve Panel (shown in modal for awaiting_review jobs)
// ---------------------------------------------------------------------------
function ApprovePanel({ jobId, onApproved }) {
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleApprove = async () => {
    setSubmitting(true);
    setError("");
    const form = new FormData();
    form.append("clinician_note", note || "Approved by clinician.");
    try {
      const res = await fetch(`${API_BASE}/intake/${jobId}/approve`, {
        method: "POST", body: form, headers: apiHeaders(),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      onApproved();
    } catch (err) {
      setError(err.message);
      setSubmitting(false);
    }
  };

  return (
    <div style={{ background: "#fff3e0", border: "2px solid #fb8c00", borderRadius: 10, padding: 20, marginTop: 20 }}>
      <div style={{ fontWeight: 700, fontSize: 14, color: "#e65100", marginBottom: 12 }}>
        ⚕ Clinician Review Required
      </div>
      <p style={{ fontSize: 13, margin: "0 0 12px", color: "#555" }}>
        This intake is paused pending your review. Add an optional note, then approve
        to resume pipeline and generate the clinical summary.
      </p>
      <textarea
        style={S.textarea}
        placeholder="Optional clinician note (e.g. 'Contacted patient, directed to ED')"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        disabled={submitting}
      />
      {error && <div style={{ color: "#e53935", fontSize: 12, marginTop: 6 }}>{error}</div>}
      <div style={{ marginTop: 12, display: "flex", gap: 10 }}>
        <button
          style={submitting ? S.btnDisabled : S.btn("#2e7d32")}
          onClick={handleApprove}
          disabled={submitting}
        >
          {submitting ? "Resuming pipeline…" : "✓ Approve & Generate Summary"}
        </button>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Detail Modal
// ---------------------------------------------------------------------------
function DetailModal({ intake, onClose, onRefresh }) {
  const [localIntake, setLocalIntake] = useState(intake);
  const [polling, setPolling] = useState(false);
  const pollRef = useRef(null);

  // When the parent refreshes the intake (after approval), sync local state
  useEffect(() => { setLocalIntake(intake); }, [intake]);

  // Start polling if job transitions to "processing" after approval
  useEffect(() => {
    if (localIntake?.status === "processing" && !polling) {
      setPolling(true);
      pollRef.current = setInterval(async () => {
        try {
          const r = await fetch(`${API_BASE}/intake/${localIntake.job_id}`, { headers: apiHeaders() });
          const updated = await r.json();
          setLocalIntake(updated);
          if (updated.status === "complete" || updated.status === "error") {
            clearInterval(pollRef.current);
            setPolling(false);
            onRefresh();
          }
        } catch (_) {}
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [localIntake?.status]);

  if (!localIntake) return null;
  const level = localIntake.risk_level || "low";
  const colors = riskColors(level);
  const isWaiting = localIntake.status === "awaiting_review";
  const isProcessing = localIntake.status === "processing";

  const handleApproved = () => {
    // Optimistically switch to processing state while we poll
    setLocalIntake((prev) => ({ ...prev, status: "processing" }));
  };

  return (
    <div style={S.modalOverlay} onClick={onClose}>
      <div style={S.modal} onClick={(e) => e.stopPropagation()}>
        <button style={S.closeBtn} onClick={onClose}>✕</button>

        <div style={{ marginBottom: 18, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={S.badge(level)}>{level}</span>
          {isWaiting && (
            <span style={{ ...S.waitingBanner, display: "inline-flex", margin: 0 }}>
              ⏸ Awaiting Clinician Review
            </span>
          )}
          {isProcessing && (
            <span style={{ background: "#1565c0", color: "#fff", fontSize: 12, fontWeight: 700, padding: "3px 10px", borderRadius: 6 }}>
              ⟳ Generating Summary…
            </span>
          )}
        </div>

        <h2 style={{ margin: "0 0 4px", fontSize: 18 }}>Patient: {localIntake.patient_id}</h2>
        <div style={{ fontSize: 12, color: "#888", marginBottom: 20 }}>
          {(localIntake.completed_at || localIntake.paused_at)
            ? new Date(localIntake.completed_at || localIntake.paused_at).toLocaleString() : ""}
          {localIntake.total_ms ? ` · Total: ${localIntake.total_ms}ms` : ""}
        </div>

        {/* Approve panel — shown only when awaiting review */}
        {isWaiting && (
          <ApprovePanel jobId={localIntake.job_id} onApproved={handleApproved} />
        )}

        {isProcessing && (
          <div style={{ ...S.statusBox, marginBottom: 20 }}>
            Generating clinical summary — this takes ~10–15s…
          </div>
        )}

        <div style={S.divider} />

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8 }}>Clinical Summary</h3>
        <div style={{
          background: colors.bg, border: `1px solid ${colors.border}`,
          borderRadius: 8, padding: 16, fontSize: 13, lineHeight: 1.7,
          whiteSpace: "pre-wrap", marginBottom: 20,
        }}>
          {localIntake.clinical_summary || (isWaiting ? "Summary will be generated after clinician approval." : "No summary available.")}
        </div>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8 }}>Clinical Signals</h3>
        <pre style={S.pre}>{JSON.stringify(localIntake.clinical_signals, null, 2)}</pre>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>Meal / Nutritional Data</h3>
        <pre style={S.pre}>{JSON.stringify(localIntake.meal_data, null, 2)}</pre>

        <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>Node Latency Breakdown</h3>
        <div style={S.latencyRow}>
          {Object.entries(localIntake.latency_ms || {}).map(([node, ms]) => (
            <span key={node} style={S.latencyChip}>{node}: {ms}ms</span>
          ))}
        </div>

        {localIntake.risk_reasons?.length > 0 && (
          <>
            <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>Risk Reasons</h3>
            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13 }}>
              {localIntake.risk_reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </>
        )}

        {localIntake.human_review_note && (
          <>
            <h3 style={{ fontSize: 14, color: "#1a237e", marginBottom: 8, marginTop: 16 }}>Review Note</h3>
            <div style={{ fontSize: 13, background: "#fff8e1", padding: 12, borderRadius: 8, border: "1px solid #fdd835" }}>
              {localIntake.human_review_note}
            </div>
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
  const isWaiting = intake.status === "awaiting_review";

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
      {isWaiting
        ? <div style={S.waitingBanner}>⏸ Awaiting Clinician Review</div>
        : intake.requires_human_review
          ? <div style={S.reviewBanner}>⚠ Review Required</div>
          : null
      }
      <div style={S.row}>
        <span style={S.badge(level)}>{level}</span>
        <strong style={{ fontSize: 14 }}>{intake.patient_id}</strong>
      </div>
      <div style={{ fontSize: 11, color: "#888", margin: "6px 0 10px" }}>
        {(intake.completed_at || intake.paused_at)
          ? new Date(intake.completed_at || intake.paused_at).toLocaleString() : ""}
      </div>
      <p style={{ fontSize: 12, margin: 0, color: "#444", lineHeight: 1.5 }}>
        {isWaiting
          ? "Pending clinician approval — click to review and approve."
          : (intake.summary_preview || "No summary available.")}
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

  // Clean up poll interval on unmount
  useEffect(() => {
    return () => {
      if (pollInterval.current) clearInterval(pollInterval.current);
    };
  }, []);

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
    // Clear any existing poll before starting a new submission
    if (pollInterval.current) clearInterval(pollInterval.current);

    setSubmitting(true);
    setPollStatus("Uploading…");

    const form = new FormData();
    form.append("audio", audioBlob, "intake.webm");
    form.append("patient_id", patientId.trim());

    try {
      const res = await fetch(`${API_BASE}/intake`, { method: "POST", body: form, headers: apiHeaders() });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setJobId(data.job_id);
      setPollStatus("Processing…");

      pollInterval.current = setInterval(async () => {
        try {
          const r = await fetch(`${API_BASE}/intake/${data.job_id}`, { headers: apiHeaders() });
          const job = await r.json();

          if (job.status === "complete") {
            clearInterval(pollInterval.current);
            setPollStatus("Complete ✓");
            setSubmitting(false);
            onSubmit();
          } else if (job.status === "awaiting_review") {
            clearInterval(pollInterval.current);
            setPollStatus("⏸ Paused — awaiting clinician review. Click card to approve.");
            setSubmitting(false);
            onSubmit();
          } else if (job.status === "error") {
            clearInterval(pollInterval.current);
            setPollStatus("Error: " + (job.error || "Unknown error"));
            setSubmitting(false);
          } else {
            const nodes = Object.keys(job.latency_ms || {});
            const last = nodes[nodes.length - 1] || "starting";
            setPollStatus(`Processing… (last: ${last})`);
          }
        } catch (_) {}
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
            <span style={S.recordingDot} />Stop Recording
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
// App (root)
// ---------------------------------------------------------------------------
export default function App() {
  const [intakes, setIntakes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedIntake, setSelectedIntake] = useState(null);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/dashboard`, { headers: apiHeaders() });
      if (res.ok) {
        const data = await res.json();
        setIntakes(data);
        // Sync selected modal if open
        if (selectedIntake) {
          const updated = data.find((j) => j.job_id === selectedIntake.job_id);
          if (updated) setSelectedIntake(updated);
        }
      }
    } catch (_) {
      // silently ignore during background polling
    } finally {
      setLoading(false);
    }
  }, [selectedIntake]);

  useEffect(() => {
    fetchDashboard();
    const id = setInterval(fetchDashboard, 10000);
    return () => clearInterval(id);
  }, [fetchDashboard]);

  const criticalCount = intakes.filter((i) => i.risk_level === "critical").length;
  const waitingCount = intakes.filter((i) => i.status === "awaiting_review").length;

  return (
    <div style={S.app}>
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        * { box-sizing: border-box; }
        body { margin: 0; }
      `}</style>

      <header style={S.header}>
        <div>
          <h1 style={S.headerTitle}>Onsera Health · Intake Agent</h1>
          <p style={S.headerSub}>Clinician Dashboard — AI-Powered Patient Check-In System</p>
        </div>
        <div style={{ marginLeft: "auto", fontSize: 13, display: "flex", gap: 16, alignItems: "center" }}>
          {criticalCount > 0 && (
            <span style={{ background: "#e53935", color: "#fff", borderRadius: 6, padding: "4px 10px", fontWeight: 700 }}>
              {criticalCount} CRITICAL
            </span>
          )}
          {waitingCount > 0 && (
            <span style={{ background: "#fb8c00", color: "#fff", borderRadius: 6, padding: "4px 10px", fontWeight: 700 }}>
              {waitingCount} awaiting review
            </span>
          )}
          <span style={{ opacity: 0.75 }}>
            {intakes.length} intake{intakes.length !== 1 ? "s" : ""}
          </span>
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
                No intakes yet. Submit a voice check-in above.
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
          onRefresh={fetchDashboard}
        />
      )}
    </div>
  );
}
