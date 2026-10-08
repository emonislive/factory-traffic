"use client";

import React from "react";

interface AlertsBannerProps {
  emergency?: {
    active: boolean;
    direction?: string | null;
    vehicle_id?: string | null;
  };
  alerts?: string[];
  connectionStatus: "connected" | "reconnecting" | "polling" | "disconnected";
}

export function AlertsBanner({ emergency, alerts = [], connectionStatus }: AlertsBannerProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px", width: "100%", marginBottom: "16px" }}>
      {/* Reconnecting / Connection Banner */}
      {connectionStatus === "reconnecting" && (
        <div
          style={{
            backgroundColor: "#78350f",
            border: "1px solid #f59e0b",
            color: "#fef3c7",
            padding: "10px 16px",
            borderRadius: "8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontWeight: 500,
            fontSize: "14px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ fontSize: "16px" }}>⚠️</span>
            <span>Connection lost. Reconnecting to live stream...</span>
          </div>
          <span style={{ fontSize: "12px", opacity: 0.8 }}>D-05 Protocol</span>
        </div>
      )}

      {connectionStatus === "polling" && (
        <div
          style={{
            backgroundColor: "#1e293b",
            border: "1px solid #38bdf8",
            color: "#e0f2fe",
            padding: "8px 16px",
            borderRadius: "8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "13px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span>🔄</span>
            <span>Live stream fallback active: polling /status every 2s</span>
          </div>
        </div>
      )}

      {/* Emergency Active Banner */}
      {emergency?.active && (
        <div
          className="flashing-emergency"
          style={{
            border: "2px solid #ef4444",
            color: "#ffffff",
            padding: "14px 20px",
            borderRadius: "8px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontWeight: "bold",
            boxShadow: "0 0 20px rgba(239, 68, 68, 0.6)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <span style={{ fontSize: "24px" }}>🚨</span>
            <div>
              <div style={{ fontSize: "18px", letterSpacing: "1px" }}>EMERGENCY PREEMPTION ACTIVE</div>
              <div style={{ fontSize: "14px", fontWeight: "normal", color: "#fecaca" }}>
                Vehicle: <strong>{emergency.vehicle_id || "EMERGENCY"}</strong> | Direction:{" "}
                <strong>{emergency.direction || "UNKNOWN"}</strong>
              </div>
            </div>
          </div>
          <div
            style={{
              backgroundColor: "#ef4444",
              color: "#ffffff",
              padding: "6px 12px",
              borderRadius: "4px",
              fontSize: "13px",
              letterSpacing: "0.5px",
            }}
          >
            PRIORITY PREEMPTION
          </div>
        </div>
      )}

      {/* Active System Alerts */}
      {alerts.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {alerts.map((alert, idx) => (
            <div
              key={idx}
              style={{
                backgroundColor: alert === "CONTROLLER_OFFLINE" || alert === "SIGNAL_FAILURE" ? "#7f1d1d" : "#78350f",
                border: `1px solid ${alert === "CONTROLLER_OFFLINE" || alert === "SIGNAL_FAILURE" ? "#dc2626" : "#d97706"}`,
                color: "#f8fafc",
                padding: "8px 14px",
                borderRadius: "6px",
                fontSize: "13px",
                display: "flex",
                alignItems: "center",
                gap: "8px",
                fontWeight: 600,
              }}
            >
              <span>⚠️</span>
              <span>ALERT: {alert}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
