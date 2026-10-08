"use client";

import React from "react";
import type { AuditLogEntry } from "@/lib/api";

interface AuditHistoryTableProps {
  entries: AuditLogEntry[];
  loading?: boolean;
}

export function AuditHistoryTable({ entries, loading = false }: AuditHistoryTableProps) {
  return (
    <div
      style={{
        backgroundColor: "#1e293b",
        border: "1px solid #334155",
        borderRadius: "10px",
        padding: "20px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
        <h3 style={{ fontSize: "16px", color: "#f8fafc", fontWeight: 600 }}>
          Recent Audit History (Append-Only Log)
        </h3>
        <span style={{ fontSize: "12px", color: "#94a3b8" }}>
          {loading ? "Refreshing..." : `${entries.length} entries shown`}
        </span>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", textAlign: "left" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #334155", color: "#94a3b8" }}>
              <th style={{ padding: "8px 12px" }}>ID</th>
              <th style={{ padding: "8px 12px" }}>Timestamp</th>
              <th style={{ padding: "8px 12px" }}>Event Type</th>
              <th style={{ padding: "8px 12px" }}>Dir</th>
              <th style={{ padding: "8px 12px" }}>Prev → New</th>
              <th style={{ padding: "8px 12px" }}>Command ID</th>
              <th style={{ padding: "8px 12px" }}>Reason / Source</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr>
                <td colSpan={7} style={{ padding: "20px", textAlign: "center", color: "#64748b" }}>
                  No audit log entries recorded yet.
                </td>
              </tr>
            ) : (
              entries.map((entry) => (
                <tr
                  key={entry.id}
                  style={{
                    borderBottom: "1px solid #1e293b",
                    color: "#f8fafc",
                    backgroundColor: "#0f172a",
                  }}
                >
                  <td style={{ padding: "8px 12px", fontFamily: "monospace", color: "#94a3b8" }}>{entry.id}</td>
                  <td style={{ padding: "8px 12px", fontSize: "12px", color: "#94a3b8" }}>
                    {new Date(entry.occurred_at).toLocaleTimeString()}
                  </td>
                  <td style={{ padding: "8px 12px", fontWeight: 600, color: "#38bdf8" }}>{entry.event_type}</td>
                  <td style={{ padding: "8px 12px" }}>{entry.direction || "-"}</td>
                  <td style={{ padding: "8px 12px" }}>
                    {entry.previous_state && entry.new_state ? (
                      <span>
                        <span style={{ color: "#94a3b8" }}>{entry.previous_state}</span> →{" "}
                        <span style={{ color: "#22c55e", fontWeight: "bold" }}>{entry.new_state}</span>
                      </span>
                    ) : (
                      entry.new_state || "-"
                    )}
                  </td>
                  <td style={{ padding: "8px 12px", fontFamily: "monospace", fontSize: "11px", color: "#94a3b8" }}>
                    {entry.command_id || "-"}
                  </td>
                  <td style={{ padding: "8px 12px", fontSize: "12px", color: "#cbd5e1" }}>
                    {entry.reason || entry.source || "-"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
