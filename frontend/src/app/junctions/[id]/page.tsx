"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  fetchJunctionStatus,
  fetchJunctionHistory,
  getStreamUrl,
} from "@/lib/api";
import type {
  JunctionStatusResponse,
  AuditLogEntry,
} from "@/lib/api";
import { IntersectionDiagram } from "@/components/IntersectionDiagram";
import { AlertsBanner } from "@/components/AlertsBanner";
import { ManualControlPanel } from "@/components/ManualControlPanel";
import { SimulationPanel } from "@/components/SimulationPanel";
import { AuditHistoryTable } from "@/components/AuditHistoryTable";

export default function JunctionDetailPage() {
  const params = useParams();
  const junctionId = (params?.id as string) || "A";

  const [status, setStatus] = useState<JunctionStatusResponse | null>(null);
  const [history, setHistory] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState<"connected" | "reconnecting" | "polling" | "disconnected">("disconnected");
  const [stepCountdown, setStepCountdown] = useState<number | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const failCountRef = useRef(0);

  const loadHistory = useCallback(async () => {
    try {
      const data = await fetchJunctionHistory(junctionId, 20);
      setHistory(data);
    } catch {
      // Ignore background refresh errors
    }
  }, [junctionId]);

  const pollStatus = useCallback(async () => {
    try {
      const data = await fetchJunctionStatus(junctionId);
      setStatus(data);
      loadHistory();
    } catch {
      // Failed poll
    }
  }, [junctionId, loadHistory]);

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) return;
    setConnectionStatus("polling");
    pollStatus();
    pollIntervalRef.current = setInterval(pollStatus, 2000);
  }, [pollStatus]);

  // Connect via SSE (with D-05 2s polling fallback)
  useEffect(() => {
    setLoading(true);
    failCountRef.current = 0;

    // Initial fetch to immediately populate UI
    fetchJunctionStatus(junctionId)
      .then((data) => {
        setStatus(data);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
    loadHistory();

    const streamUrl = getStreamUrl(junctionId);
    let es: EventSource | null = null;

    try {
      es = new EventSource(streamUrl);
      eventSourceRef.current = es;

      es.onopen = () => {
        failCountRef.current = 0;
        setConnectionStatus("connected");
      };

      es.addEventListener("status", (event: MessageEvent) => {
        try {
          const data: JunctionStatusResponse = JSON.parse(event.data);
          setStatus(data);
          loadHistory();
        } catch {
          // ignore malformed SSE payload
        }
      });

      es.onerror = () => {
        failCountRef.current += 1;
        if (failCountRef.current >= 2) {
          if (es) {
            es.close();
            eventSourceRef.current = null;
          }
          startPolling();
        } else {
          setConnectionStatus("reconnecting");
        }
      };
    } catch {
      startPolling();
    }

    return () => {
      if (es) {
        es.close();
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [junctionId, loadHistory, startPolling]);

  // Live transition countdown to deadline_at
  useEffect(() => {
    if (!status?.transition?.deadline_at) {
      setStepCountdown(null);
      return;
    }

    const interval = setInterval(() => {
      const remaining = Math.max(0, Math.ceil(status.transition.deadline_at! - Date.now() / 1000));
      setStepCountdown(remaining);
    }, 200);

    return () => clearInterval(interval);
  }, [status?.transition?.deadline_at]);

  if (loading && !status) {
    return (
      <main style={{ maxWidth: "1200px", margin: "0 auto", padding: "40px 20px", textAlign: "center" }}>
        <p style={{ color: "#94a3b8" }}>Connecting to Junction {junctionId}...</p>
      </main>
    );
  }

  const desired = status?.desired_signals || {};
  const actual = status?.actual_signals || {};
  const queues = status?.queues || {};
  const transition = status?.transition;

  return (
    <main style={{ maxWidth: "1280px", margin: "0 auto", padding: "24px 20px" }}>
      {/* Top Navigation & Status Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "20px",
          borderBottom: "1px solid #334155",
          paddingBottom: "16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <Link
            href="/"
            style={{
              fontSize: "14px",
              color: "#38bdf8",
              display: "flex",
              alignItems: "center",
              gap: "4px",
            }}
          >
            ← Back to Overview
          </Link>
          <span style={{ color: "#475569" }}>|</span>
          <h1 style={{ fontSize: "22px", fontWeight: "bold", color: "#f8fafc" }}>
            Junction {junctionId} Control & Telemetry
          </h1>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          {/* Connection Status Badge */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              fontSize: "12px",
              padding: "4px 10px",
              borderRadius: "12px",
              backgroundColor:
                connectionStatus === "connected"
                  ? "rgba(34, 197, 94, 0.15)"
                  : connectionStatus === "polling"
                  ? "rgba(56, 189, 248, 0.15)"
                  : "rgba(234, 179, 8, 0.15)",
              color:
                connectionStatus === "connected"
                  ? "#22c55e"
                  : connectionStatus === "polling"
                  ? "#38bdf8"
                  : "#eab308",
              border: `1px solid ${
                connectionStatus === "connected"
                  ? "#22c55e"
                  : connectionStatus === "polling"
                  ? "#38bdf8"
                  : "#eab308"
              }`,
            }}
          >
            <span
              style={{
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                backgroundColor:
                  connectionStatus === "connected"
                    ? "#22c55e"
                    : connectionStatus === "polling"
                    ? "#38bdf8"
                    : "#eab308",
              }}
            />
            {connectionStatus === "connected"
              ? "Live SSE Stream"
              : connectionStatus === "polling"
              ? "Polling Fallback (2s)"
              : "Reconnecting..."}
          </div>

          {/* Mode Badge */}
          <div
            style={{
              fontSize: "12px",
              fontWeight: 700,
              padding: "4px 12px",
              borderRadius: "12px",
              backgroundColor:
                status?.mode === "EMERGENCY"
                  ? "rgba(239, 68, 68, 0.2)"
                  : status?.mode === "DEGRADED"
                  ? "rgba(220, 38, 38, 0.3)"
                  : status?.mode === "MANUAL"
                  ? "rgba(234, 179, 8, 0.2)"
                  : "rgba(34, 197, 94, 0.15)",
              color:
                status?.mode === "EMERGENCY"
                  ? "#ef4444"
                  : status?.mode === "DEGRADED"
                  ? "#fca5a5"
                  : status?.mode === "MANUAL"
                  ? "#eab308"
                  : "#22c55e",
              border: "1px solid currentColor",
            }}
          >
            MODE: {status?.mode || "AUTOMATIC"}
          </div>
        </div>
      </div>

      {/* Transition Banner */}
      <div
        style={{
          backgroundColor: "#1e293b",
          border: "1px solid #334155",
          borderRadius: "8px",
          padding: "12px 20px",
          marginBottom: "16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
          <div>
            <span style={{ fontSize: "12px", color: "#94a3b8" }}>Active Step:</span>{" "}
            <strong
              style={{
                fontSize: "15px",
                color:
                  transition?.step === "GREEN"
                    ? "#22c55e"
                    : transition?.step === "YELLOW"
                    ? "#eab308"
                    : "#ef4444",
              }}
            >
              {transition?.step || "BOOT"}
            </strong>
          </div>
          <div>
            <span style={{ fontSize: "12px", color: "#94a3b8" }}>Serving:</span>{" "}
            <strong style={{ fontSize: "15px", color: "#f8fafc" }}>{status?.phase || "N/A"}</strong>
          </div>
          {transition?.target && (
            <div>
              <span style={{ fontSize: "12px", color: "#94a3b8" }}>Target Phase:</span>{" "}
              <strong style={{ fontSize: "15px", color: "#38bdf8" }}>{transition.target}</strong>
            </div>
          )}
        </div>

        {stepCountdown !== null && (
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "12px", color: "#94a3b8" }}>Step Countdown:</span>
            <span
              style={{
                fontFamily: "monospace",
                fontSize: "18px",
                fontWeight: "bold",
                color: "#eab308",
                backgroundColor: "#0f172a",
                padding: "2px 8px",
                borderRadius: "4px",
                border: "1px solid #334155",
              }}
            >
              {stepCountdown}s
            </span>
          </div>
        )}
      </div>

      {/* Alerts and Emergency Banner */}
      <AlertsBanner
        emergency={status?.emergency}
        alerts={status?.alerts}
        connectionStatus={connectionStatus}
      />

      {/* Main Grid: Visual Intersection (Left) & Controls (Right) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(380px, 1.2fr) minmax(360px, 1fr)",
          gap: "24px",
          marginBottom: "24px",
        }}
      >
        {/* Left Column: Intersection Visual Diagram */}
        <div>
          <IntersectionDiagram
            desired={desired}
            actual={actual}
            queues={queues}
            activePhase={status?.phase}
            step={transition?.step}
          />
        </div>

        {/* Right Column: Controls */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          {/* Manual Control Panel */}
          <ManualControlPanel
            junctionId={junctionId}
            mode={status?.mode || "AUTOMATIC"}
            manual={status?.manual}
            onCommandSent={pollStatus}
          />

          {/* Simulation & Hardware Controls */}
          <SimulationPanel
            junctionId={junctionId}
            onEventSent={pollStatus}
          />
        </div>
      </div>

      {/* Bottom Section: Append-Only Audit History Table */}
      <AuditHistoryTable entries={history} />
    </main>
  );
}
