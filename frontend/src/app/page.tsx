"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { fetchJunctions, fetchJunctionStatus } from "@/lib/api";
import type { JunctionSummary, JunctionStatusResponse } from "@/lib/api";

interface JunctionWithStatus {
  summary: JunctionSummary;
  status?: JunctionStatusResponse;
  error?: string;
}

export default function HomePage() {
  const [junctions, setJunctions] = useState<JunctionWithStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async () => {
    try {
      const summaries = await fetchJunctions();
      const withStatus = await Promise.all(
        summaries.map(async (j) => {
          try {
            const status = await fetchJunctionStatus(j.id);
            return { summary: j, status };
          } catch {
            return { summary: j, error: "Status offline" };
          }
        })
      );
      setJunctions(withStatus);
    } catch {
      setJunctions([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 3000);
    return () => clearInterval(interval);
  }, []);

  const getModeColor = (mode?: string) => {
    switch (mode) {
      case "AUTOMATIC":
        return { bg: "rgba(34, 197, 94, 0.15)", text: "#22c55e", border: "#22c55e" };
      case "EMERGENCY":
        return { bg: "rgba(239, 68, 68, 0.2)", text: "#ef4444", border: "#ef4444" };
      case "MANUAL":
        return { bg: "rgba(234, 179, 8, 0.2)", text: "#eab308", border: "#eab308" };
      case "DEGRADED":
        return { bg: "rgba(220, 38, 38, 0.3)", text: "#fca5a5", border: "#dc2626" };
      default:
        return { bg: "rgba(100, 116, 139, 0.2)", text: "#94a3b8", border: "#64748b" };
    }
  };

  return (
    <main style={{ maxWidth: "1200px", margin: "0 auto", padding: "32px 20px" }}>
      {/* Header */}
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "32px",
          borderBottom: "1px solid #334155",
          paddingBottom: "20px",
        }}
      >
        <div>
          <h1 style={{ fontSize: "28px", fontWeight: "bold", color: "#f8fafc" }}>
            Factory Traffic Management System
          </h1>
          <p style={{ color: "#94a3b8", fontSize: "14px", marginTop: "4px" }}>
            Real-time intersection coordination, safety invariants & fault-tolerant control
          </p>
        </div>
        <button
          onClick={() => {
            setRefreshing(true);
            loadData();
          }}
          style={{
            backgroundColor: "#1e293b",
            color: "#38bdf8",
            border: "1px solid #38bdf8",
            display: "flex",
            alignItems: "center",
            gap: "6px",
          }}
        >
          {refreshing ? "Refreshing..." : "↻ Refresh Dashboard"}
        </button>
      </header>

      {/* Junctions Grid */}
      {loading ? (
        <div style={{ padding: "40px", textAlign: "center", color: "#94a3b8" }}>
          Loading factory junctions...
        </div>
      ) : junctions.length === 0 ? (
        <div
          style={{
            backgroundColor: "#1e293b",
            border: "1px dashed #475569",
            borderRadius: "12px",
            padding: "40px",
            textAlign: "center",
          }}
        >
          <h3 style={{ color: "#f8fafc", marginBottom: "8px" }}>No Junctions Configured</h3>
          <p style={{ color: "#94a3b8", fontSize: "14px", marginBottom: "20px" }}>
            Run database seed script or initialize Junction A via API.
          </p>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))",
            gap: "24px",
          }}
        >
          {junctions.map(({ summary, status }) => {
            const modeStyle = getModeColor(status?.mode);
            const totalQueued = status?.queues
              ? Object.values(status.queues).reduce((acc: number, val) => acc + (val || 0), 0)
              : 0;

            return (
              <div
                key={summary.id}
                style={{
                  backgroundColor: "#1e293b",
                  border: status?.emergency?.active
                    ? "2px solid #ef4444"
                    : status?.mode === "DEGRADED"
                    ? "2px solid #dc2626"
                    : "1px solid #334155",
                  borderRadius: "12px",
                  padding: "24px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.3)",
                }}
              >
                <div>
                  {/* Top Bar: ID + Name + Mode */}
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "flex-start",
                      marginBottom: "16px",
                    }}
                  >
                    <div>
                      <span
                        style={{
                          fontSize: "12px",
                          fontWeight: 700,
                          backgroundColor: "#0f172a",
                          color: "#38bdf8",
                          padding: "2px 8px",
                          borderRadius: "4px",
                          border: "1px solid #1e293b",
                        }}
                      >
                        JUNCTION {summary.id}
                      </span>
                      <h2 style={{ fontSize: "18px", color: "#f8fafc", marginTop: "6px" }}>
                        {summary.name}
                      </h2>
                    </div>
                    <span
                      style={{
                        fontSize: "12px",
                        fontWeight: 700,
                        backgroundColor: modeStyle.bg,
                        color: modeStyle.text,
                        border: `1px solid ${modeStyle.border}`,
                        padding: "3px 10px",
                        borderRadius: "12px",
                      }}
                    >
                      {status?.mode || "UNKNOWN"}
                    </span>
                  </div>

                  {/* Active Emergency / Degradation Banner */}
                  {status?.emergency?.active && (
                    <div
                      className="flashing-emergency"
                      style={{
                        padding: "6px 12px",
                        borderRadius: "6px",
                        fontSize: "12px",
                        fontWeight: "bold",
                        color: "#ffffff",
                        marginBottom: "12px",
                        textAlign: "center",
                      }}
                    >
                      EMERGENCY ACTIVE ({status.emergency.direction})
                    </div>
                  )}

                  {/* Junction Details Grid */}
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: "12px",
                      fontSize: "13px",
                      marginBottom: "16px",
                      backgroundColor: "#0f172a",
                      padding: "12px",
                      borderRadius: "8px",
                    }}
                  >
                    <div>
                      <span style={{ color: "#94a3b8" }}>Serving:</span>{" "}
                      <strong style={{ color: "#f8fafc" }}>{status?.phase || "N/A"}</strong>
                    </div>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Step:</span>{" "}
                      <strong
                        style={{
                          color:
                            status?.transition?.step === "GREEN"
                              ? "#22c55e"
                              : status?.transition?.step === "YELLOW"
                              ? "#eab308"
                              : "#ef4444",
                        }}
                      >
                        {status?.transition?.step || "BOOT"}
                      </strong>
                    </div>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Controller:</span>{" "}
                      <strong
                        style={{
                          color: status?.controller_status === "ONLINE" ? "#22c55e" : "#ef4444",
                        }}
                      >
                        {status?.controller_status || "UNKNOWN"}
                      </strong>
                    </div>
                    <div>
                      <span style={{ color: "#94a3b8" }}>Total Queue:</span>{" "}
                      <strong style={{ color: "#38bdf8" }}>{totalQueued} vehicles</strong>
                    </div>
                  </div>

                  {/* Direction Queues */}
                  {status?.queues && (
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: "12px",
                        color: "#94a3b8",
                        marginBottom: "16px",
                        padding: "0 4px",
                      }}
                    >
                      <span>N: <strong style={{ color: "#f8fafc" }}>{status.queues.NORTH || 0}</strong></span>
                      <span>S: <strong style={{ color: "#f8fafc" }}>{status.queues.SOUTH || 0}</strong></span>
                      <span>E: <strong style={{ color: "#f8fafc" }}>{status.queues.EAST || 0}</strong></span>
                      <span>W: <strong style={{ color: "#f8fafc" }}>{status.queues.WEST || 0}</strong></span>
                    </div>
                  )}

                  {/* Active Alerts */}
                  {status?.alerts && status.alerts.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "16px" }}>
                      {status.alerts.map((alert: string, idx: number) => (
                        <span
                          key={idx}
                          style={{
                            fontSize: "11px",
                            padding: "2px 6px",
                            backgroundColor: "#7f1d1d",
                            color: "#fecaca",
                            borderRadius: "4px",
                            fontWeight: 600,
                          }}
                        >
                          ⚠️ {alert}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Link to detail page */}
                <Link
                  href={`/junctions/${summary.id}`}
                  style={{
                    display: "block",
                    backgroundColor: "#0284c7",
                    color: "white",
                    padding: "10px",
                    borderRadius: "6px",
                    textAlign: "center",
                    fontWeight: 600,
                    fontSize: "14px",
                  }}
                >
                  Open Junction Control Panel →
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
