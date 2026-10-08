"use client";

import React from "react";
import type { Direction, Signal } from "@/lib/api";

interface IntersectionDiagramProps {
  desired: Record<string, Signal | undefined>;
  actual: Record<string, Signal | undefined>;
  queues: Record<string, number | undefined>;
  activePhase?: string;
  step?: string;
}

function getSignalColor(signal?: Signal): { bg: string; border: string; glow: string } {
  switch (signal) {
    case "GREEN":
      return { bg: "#22c55e", border: "#16a34a", glow: "0 0 16px rgba(34, 197, 94, 0.8)" };
    case "YELLOW":
      return { bg: "#eab308", border: "#ca8a04", glow: "0 0 16px rgba(234, 179, 8, 0.8)" };
    case "RED":
      return { bg: "#ef4444", border: "#dc2626", glow: "0 0 16px rgba(239, 68, 68, 0.8)" };
    default:
      return { bg: "#64748b", border: "#475569", glow: "none" };
  }
}

interface SignalHeadProps {
  direction: Direction;
  desired?: Signal;
  actual?: Signal;
  queue?: number;
}

function SignalHead({ direction, desired, actual, queue = 0 }: SignalHeadProps) {
  const isMismatch = desired && actual && desired !== actual && actual !== "UNKNOWN";
  const actualStyle = getSignalColor(actual);
  const desiredStyle = getSignalColor(desired);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "10px 14px",
        backgroundColor: "#1e293b",
        border: isMismatch ? "2px solid #ef4444" : "1px solid #334155",
        borderRadius: "8px",
        boxShadow: isMismatch ? "0 0 12px rgba(239, 68, 68, 0.5)" : "0 4px 6px rgba(0, 0, 0, 0.3)",
        minWidth: "130px",
      }}
    >
      <div style={{ fontWeight: "bold", fontSize: "14px", color: "#f8fafc", marginBottom: "6px" }}>
        {direction}
      </div>

      {/* Traffic Light Head */}
      <div
        style={{
          display: "flex",
          gap: "6px",
          backgroundColor: "#020617",
          padding: "6px 10px",
          borderRadius: "16px",
          border: "1px solid #1e293b",
          marginBottom: "8px",
        }}
      >
        {/* RED lamp */}
        <div
          title="RED"
          style={{
            width: "18px",
            height: "18px",
            borderRadius: "50%",
            backgroundColor: actual === "RED" ? "#ef4444" : "#450a0a",
            boxShadow: actual === "RED" ? "0 0 10px #ef4444" : "none",
            border: "1px solid #7f1d1d",
          }}
        />
        {/* YELLOW lamp */}
        <div
          title="YELLOW"
          style={{
            width: "18px",
            height: "18px",
            borderRadius: "50%",
            backgroundColor: actual === "YELLOW" ? "#eab308" : "#422006",
            boxShadow: actual === "YELLOW" ? "0 0 10px #eab308" : "none",
            border: "1px solid #713f12",
          }}
        />
        {/* GREEN lamp */}
        <div
          title="GREEN"
          style={{
            width: "18px",
            height: "18px",
            borderRadius: "50%",
            backgroundColor: actual === "GREEN" ? "#22c55e" : "#052e16",
            boxShadow: actual === "GREEN" ? "0 0 10px #22c55e" : "none",
            border: "1px solid #14532d",
          }}
        />
      </div>

      <div style={{ fontSize: "12px", width: "100%", display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
        <span style={{ color: "#94a3b8" }}>Desired:</span>
        <span style={{ fontWeight: 600, color: desiredStyle.bg }}>{desired || "N/A"}</span>
      </div>

      <div style={{ fontSize: "12px", width: "100%", display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
        <span style={{ color: "#94a3b8" }}>Actual:</span>
        <span style={{ fontWeight: 600, color: actualStyle.bg }}>{actual || "N/A"}</span>
      </div>

      {isMismatch && (
        <div
          style={{
            backgroundColor: "#7f1d1d",
            color: "#fecaca",
            fontSize: "10px",
            padding: "2px 6px",
            borderRadius: "4px",
            fontWeight: "bold",
            marginBottom: "6px",
            textAlign: "center",
          }}
        >
          SIGNAL MISMATCH
        </div>
      )}

      {/* Queue Tag */}
      <div
        style={{
          backgroundColor: queue > 0 ? "rgba(56, 189, 248, 0.2)" : "#0f172a",
          border: `1px solid ${queue > 0 ? "#38bdf8" : "#334155"}`,
          color: queue > 0 ? "#38bdf8" : "#64748b",
          fontSize: "12px",
          padding: "3px 8px",
          borderRadius: "12px",
          fontWeight: 600,
          marginTop: "auto",
        }}
      >
        Waiting: {queue}
      </div>
    </div>
  );
}

export function IntersectionDiagram({ desired, actual, queues, activePhase, step }: IntersectionDiagramProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#0b1329",
        borderRadius: "12px",
        padding: "24px",
        border: "1px solid #1e293b",
        position: "relative",
        minHeight: "480px",
      }}
    >
      {/* NORTH */}
      <div style={{ marginBottom: "16px" }}>
        <SignalHead
          direction="NORTH"
          desired={desired.NORTH}
          actual={actual.NORTH}
          queue={queues.NORTH || 0}
        />
      </div>

      {/* MIDDLE ROW: WEST, CROSSING CENTER, EAST */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "24px", width: "100%" }}>
        {/* WEST */}
        <SignalHead
          direction="WEST"
          desired={desired.WEST}
          actual={actual.WEST}
          queue={queues.WEST || 0}
        />

        {/* INTERSECTION CENTER */}
        <div
          style={{
            width: "140px",
            height: "140px",
            backgroundColor: "#1e293b",
            border: "2px dashed #475569",
            borderRadius: "12px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "inset 0 0 20px rgba(0, 0, 0, 0.5)",
            textAlign: "center",
            padding: "8px",
          }}
        >
          <div style={{ fontSize: "11px", color: "#94a3b8", textTransform: "uppercase", letterSpacing: "1px" }}>
            Serving Phase
          </div>
          <div style={{ fontSize: "20px", fontWeight: "bold", color: "#38bdf8", margin: "4px 0" }}>
            {activePhase || "NONE"}
          </div>
          <div
            style={{
              fontSize: "11px",
              padding: "2px 8px",
              borderRadius: "10px",
              fontWeight: 600,
              backgroundColor: step === "GREEN" ? "rgba(34, 197, 94, 0.2)" : step === "YELLOW" ? "rgba(234, 179, 8, 0.2)" : "rgba(239, 68, 68, 0.2)",
              color: step === "GREEN" ? "#22c55e" : step === "YELLOW" ? "#eab308" : "#ef4444",
            }}
          >
            STEP: {step || "BOOT"}
          </div>
        </div>

        {/* EAST */}
        <SignalHead
          direction="EAST"
          desired={desired.EAST}
          actual={actual.EAST}
          queue={queues.EAST || 0}
        />
      </div>

      {/* SOUTH */}
      <div style={{ marginTop: "16px" }}>
        <SignalHead
          direction="SOUTH"
          desired={desired.SOUTH}
          actual={actual.SOUTH}
          queue={queues.SOUTH || 0}
        />
      </div>
    </div>
  );
}
