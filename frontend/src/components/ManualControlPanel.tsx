"use client";

import React, { useState, useEffect } from "react";
import { requestManualGreen, returnToAutomatic } from "@/lib/api";
import type { Direction, Mode } from "@/lib/api";

interface ManualControlPanelProps {
  junctionId: string;
  mode: Mode;
  manual?: {
    active: boolean;
    lease_expires_at?: number | null;
    issued_by?: string | null;
  };
  onCommandSent?: () => void;
}

export function ManualControlPanel({ junctionId, mode, manual, onCommandSent }: ManualControlPanelProps) {
  const [selectedDirection, setSelectedDirection] = useState<Direction>("NORTH");
  const [issuedBy, setIssuedBy] = useState("operator-1");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [secondsRemaining, setSecondsRemaining] = useState<number | null>(null);

  // Countdown timer for manual lease
  useEffect(() => {
    if (!manual?.active || !manual?.lease_expires_at) {
      setSecondsRemaining(null);
      return;
    }

    const interval = setInterval(() => {
      const remaining = Math.max(0, Math.ceil(manual.lease_expires_at! - Date.now() / 1000));
      setSecondsRemaining(remaining);
    }, 500);

    return () => clearInterval(interval);
  }, [manual?.active, manual?.lease_expires_at]);

  const handleRequestGreen = async () => {
    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      await requestManualGreen(junctionId, selectedDirection, issuedBy);
      setSuccessMsg(`Requested Manual Green for ${selectedDirection}`);
      onCommandSent?.();
    } catch (err: unknown) {
      const e = err as Error;
      setErrorMsg(e.message || "Failed to request manual green");
    } finally {
      setLoading(false);
    }
  };

  const handleReturnToAutomatic = async () => {
    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      await returnToAutomatic(junctionId, issuedBy);
      setSuccessMsg("Returned junction to AUTOMATIC control");
      onCommandSent?.();
    } catch (err: unknown) {
      const e = err as Error;
      setErrorMsg(e.message || "Failed to return to automatic");
    } finally {
      setLoading(false);
    }
  };

  const isDegraded = mode === "DEGRADED";

  return (
    <div
      style={{
        backgroundColor: "#1e293b",
        border: "1px solid #334155",
        borderRadius: "10px",
        padding: "20px",
        marginBottom: "20px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h3 style={{ fontSize: "16px", color: "#f8fafc", fontWeight: 600 }}>Manual Override Control Panel</h3>
        <span
          style={{
            fontSize: "12px",
            padding: "4px 10px",
            borderRadius: "12px",
            fontWeight: 600,
            backgroundColor: manual?.active ? "rgba(234, 179, 8, 0.2)" : "rgba(100, 116, 139, 0.2)",
            color: manual?.active ? "#eab308" : "#94a3b8",
            border: `1px solid ${manual?.active ? "#ca8a04" : "#475569"}`,
          }}
        >
          {manual?.active ? "MANUAL LEASE ACTIVE" : "AUTOMATIC"}
        </span>
      </div>

      {isDegraded && (
        <div
          style={{
            backgroundColor: "#450a0a",
            color: "#fca5a5",
            padding: "8px 12px",
            borderRadius: "6px",
            fontSize: "13px",
            marginBottom: "14px",
            border: "1px solid #991b1b",
          }}
        >
          Junction is DEGRADED. Manual commands will be rejected with 409 CONFLICT (P-04).
        </div>
      )}

      {manual?.active && (
        <div
          style={{
            backgroundColor: "#2e2107",
            border: "1px solid #b45309",
            color: "#fde68a",
            padding: "10px 14px",
            borderRadius: "6px",
            fontSize: "13px",
            marginBottom: "16px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <span>Issued by: <strong>{manual.issued_by || "Unknown"}</strong></span>
          </div>
          <div>
            <span>Lease Expires in: <strong>{secondsRemaining !== null ? `${secondsRemaining}s` : "N/A"}</strong></span>
          </div>
        </div>
      )}

      {errorMsg && (
        <div
          style={{
            backgroundColor: "#450a0a",
            color: "#fca5a5",
            padding: "8px 12px",
            borderRadius: "6px",
            fontSize: "13px",
            marginBottom: "12px",
          }}
        >
          {errorMsg}
        </div>
      )}

      {successMsg && (
        <div
          style={{
            backgroundColor: "#052e16",
            color: "#86efac",
            padding: "8px 12px",
            borderRadius: "6px",
            fontSize: "13px",
            marginBottom: "12px",
          }}
        >
          {successMsg}
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", alignItems: "flex-end" }}>
        <div>
          <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "4px" }}>
            Target Direction
          </label>
          <select
            value={selectedDirection}
            onChange={(e) => setSelectedDirection(e.target.value as Direction)}
            disabled={loading || isDegraded}
            style={{ width: "120px" }}
          >
            <option value="NORTH">NORTH</option>
            <option value="SOUTH">SOUTH</option>
            <option value="EAST">EAST</option>
            <option value="WEST">WEST</option>
          </select>
        </div>

        <div>
          <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "4px" }}>
            Issued By
          </label>
          <input
            type="text"
            value={issuedBy}
            onChange={(e) => setIssuedBy(e.target.value)}
            disabled={loading || isDegraded}
            placeholder="Operator ID"
            style={{ width: "130px" }}
          />
        </div>

        <button
          onClick={handleRequestGreen}
          disabled={loading || isDegraded}
          style={{
            backgroundColor: "#0284c7",
            color: "white",
            border: "none",
            height: "36px",
          }}
        >
          {loading ? "Sending..." : "Request Manual Green"}
        </button>

        <button
          onClick={handleReturnToAutomatic}
          disabled={loading}
          style={{
            backgroundColor: "#334155",
            color: "#f8fafc",
            border: "1px solid #475569",
            height: "36px",
          }}
        >
          Return to Automatic
        </button>
      </div>
    </div>
  );
}
