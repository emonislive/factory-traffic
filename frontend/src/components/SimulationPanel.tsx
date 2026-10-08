"use client";

import React, { useState } from "react";
import {
  ingestVehicleArrival,
  ingestVehicleClearance,
  setSimulatorMode,
  reportDeviceStatus,
  sendControllerAck,
} from "@/lib/api";
import type { Direction, VehicleType } from "@/lib/api";

interface SimulationPanelProps {
  junctionId: string;
  onEventSent?: () => void;
}

export function SimulationPanel({ junctionId, onEventSent }: SimulationPanelProps) {
  const [isOpen, setIsOpen] = useState(true);

  // Arrival form state
  const [arrDir, setArrDir] = useState<Direction>("NORTH");
  const [arrType, setArrType] = useState<VehicleType>("TRUCK");
  const [arrVehId, setArrVehId] = useState("VH-101");
  const [arrSeq, setArrSeq] = useState(1);

  // Clearance form state
  const [clrDir, setClrDir] = useState<Direction>("NORTH");
  const [clrVehId, setClrVehId] = useState("VH-101");
  const [clrSeq, setClrSeq] = useState(2);

  // Simulator mode
  const [simMode, setSimMode] = useState<"AUTO_ACK" | "DELAYED" | "SILENT" | "OFFLINE">("AUTO_ACK");

  // Device status
  const [devStatus, setDevStatus] = useState<"ONLINE" | "OFFLINE" | "DEGRADED">("ONLINE");

  // ACK injector
  const [ackCmdId, setAckCmdId] = useState("");
  const [ackDir, setAckDir] = useState<Direction>("NORTH");
  const [ackStatus, setAckStatus] = useState<"ACK" | "NACK">("ACK");
  const [ackActualState, setAckActualState] = useState("GREEN");

  const [statusMsg, setStatusMsg] = useState<{ text: string; isError: boolean } | null>(null);

  const showFeedback = (text: string, isError = false) => {
    setStatusMsg({ text, isError });
    setTimeout(() => setStatusMsg(null), 4000);
  };

  const handleArrival = async () => {
    try {
      const res = await ingestVehicleArrival(junctionId, arrDir, arrType, arrVehId, arrSeq);
      showFeedback(`Arrival recorded: ${arrVehId} (${arrType}) on ${arrDir} [Status: ${res.status}]`);
      setArrSeq((s) => s + 1);
      onEventSent?.();
    } catch (e: unknown) {
      showFeedback((e as Error).message, true);
    }
  };

  const handleClearance = async () => {
    try {
      const res = await ingestVehicleClearance(junctionId, clrDir, clrVehId, clrSeq);
      showFeedback(`Clearance recorded: ${clrVehId} on ${clrDir} [Status: ${res.status}]`);
      setClrSeq((s) => s + 1);
      onEventSent?.();
    } catch (e: unknown) {
      showFeedback((e as Error).message, true);
    }
  };

  const handleSetSimMode = async () => {
    try {
      await setSimulatorMode(junctionId, simMode);
      showFeedback(`Controller simulator mode set to ${simMode}`);
      onEventSent?.();
    } catch (e: unknown) {
      showFeedback((e as Error).message, true);
    }
  };

  const handleReportDevStatus = async () => {
    try {
      await reportDeviceStatus(junctionId, "SIGNAL_CONTROLLER", devStatus);
      showFeedback(`Signal controller status reported as ${devStatus}`);
      onEventSent?.();
    } catch (e: unknown) {
      showFeedback((e as Error).message, true);
    }
  };

  const handleSendAck = async () => {
    if (!ackCmdId) {
      showFeedback("Please provide a Command ID", true);
      return;
    }
    try {
      await sendControllerAck(ackCmdId, junctionId, ackDir, ackStatus, ackActualState);
      showFeedback(`Submitted ${ackStatus} for command ${ackCmdId}`);
      onEventSent?.();
    } catch (e: unknown) {
      showFeedback((e as Error).message, true);
    }
  };

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
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: "pointer",
        }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <h3 style={{ fontSize: "16px", color: "#f8fafc", fontWeight: 600 }}>
          Simulation & Hardware Injection Controls
        </h3>
        <button
          style={{
            background: "none",
            border: "none",
            color: "#94a3b8",
            fontSize: "14px",
            padding: "4px 8px",
          }}
        >
          {isOpen ? "▲ Collapse" : "▼ Expand"}
        </button>
      </div>

      {statusMsg && (
        <div
          style={{
            marginTop: "12px",
            padding: "8px 12px",
            borderRadius: "6px",
            fontSize: "13px",
            backgroundColor: statusMsg.isError ? "#450a0a" : "#052e16",
            color: statusMsg.isError ? "#fca5a5" : "#86efac",
            border: `1px solid ${statusMsg.isError ? "#b91c1c" : "#15803d"}`,
          }}
        >
          {statusMsg.text}
        </div>
      )}

      {isOpen && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: "20px",
            marginTop: "16px",
          }}
        >
          {/* Card 1: Ingest Arrival */}
          <div style={{ backgroundColor: "#0f172a", padding: "14px", borderRadius: "8px", border: "1px solid #334155" }}>
            <h4 style={{ fontSize: "13px", color: "#38bdf8", marginBottom: "10px" }}>1. Simulate Vehicle Arrival</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div style={{ display: "flex", gap: "8px" }}>
                <select value={arrDir} onChange={(e) => setArrDir(e.target.value as Direction)} style={{ flex: 1 }}>
                  <option value="NORTH">NORTH</option>
                  <option value="SOUTH">SOUTH</option>
                  <option value="EAST">EAST</option>
                  <option value="WEST">WEST</option>
                </select>
                <select value={arrType} onChange={(e) => setArrType(e.target.value as VehicleType)} style={{ flex: 1 }}>
                  <option value="TRUCK">TRUCK</option>
                  <option value="EMERGENCY">EMERGENCY</option>
                  <option value="FORKLIFT">FORKLIFT</option>
                  <option value="EMPLOYEE_VEHICLE">EMPLOYEE</option>
                </select>
              </div>
              <div style={{ display: "flex", gap: "8px" }}>
                <input
                  type="text"
                  value={arrVehId}
                  onChange={(e) => setArrVehId(e.target.value)}
                  placeholder="Vehicle ID"
                  style={{ flex: 1 }}
                />
                <input
                  type="number"
                  value={arrSeq}
                  onChange={(e) => setArrSeq(parseInt(e.target.value) || 0)}
                  placeholder="Seq"
                  style={{ width: "70px" }}
                />
              </div>
              <button
                onClick={handleArrival}
                style={{ backgroundColor: "#0284c7", color: "white", border: "none", marginTop: "4px" }}
              >
                Send Arrival Event
              </button>
            </div>
          </div>

          {/* Card 2: Ingest Clearance */}
          <div style={{ backgroundColor: "#0f172a", padding: "14px", borderRadius: "8px", border: "1px solid #334155" }}>
            <h4 style={{ fontSize: "13px", color: "#38bdf8", marginBottom: "10px" }}>2. Simulate Vehicle Clearance</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div style={{ display: "flex", gap: "8px" }}>
                <select value={clrDir} onChange={(e) => setClrDir(e.target.value as Direction)} style={{ flex: 1 }}>
                  <option value="NORTH">NORTH</option>
                  <option value="SOUTH">SOUTH</option>
                  <option value="EAST">EAST</option>
                  <option value="WEST">WEST</option>
                </select>
                <input
                  type="text"
                  value={clrVehId}
                  onChange={(e) => setClrVehId(e.target.value)}
                  placeholder="Vehicle ID"
                  style={{ flex: 1 }}
                />
              </div>
              <input
                type="number"
                value={clrSeq}
                onChange={(e) => setClrSeq(parseInt(e.target.value) || 0)}
                placeholder="Clearance Seq"
              />
              <button
                onClick={handleClearance}
                style={{ backgroundColor: "#15803d", color: "white", border: "none", marginTop: "4px" }}
              >
                Send Clearance Event
              </button>
            </div>
          </div>

          {/* Card 3: Simulator Controller Mode */}
          <div style={{ backgroundColor: "#0f172a", padding: "14px", borderRadius: "8px", border: "1px solid #334155" }}>
            <h4 style={{ fontSize: "13px", color: "#38bdf8", marginBottom: "10px" }}>3. Hardware Simulator Mode (D-04)</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <select
                value={simMode}
                onChange={(e) => setSimMode(e.target.value as "AUTO_ACK" | "DELAYED" | "SILENT" | "OFFLINE")}
              >
                <option value="AUTO_ACK">AUTO_ACK (Instant normal)</option>
                <option value="DELAYED">DELAYED (Simulate lag)</option>
                <option value="SILENT">SILENT (Drop commands / timeout)</option>
                <option value="OFFLINE">OFFLINE (Simulate disconnect)</option>
              </select>
              <button
                onClick={handleSetSimMode}
                style={{ backgroundColor: "#b45309", color: "white", border: "none", marginTop: "4px" }}
              >
                Update Simulator Mode
              </button>
            </div>
          </div>

          {/* Card 4: Device Health & ACK Injector */}
          <div style={{ backgroundColor: "#0f172a", padding: "14px", borderRadius: "8px", border: "1px solid #334155" }}>
            <h4 style={{ fontSize: "13px", color: "#38bdf8", marginBottom: "10px" }}>4. Hardware Status & ACK Injector</h4>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div style={{ display: "flex", gap: "8px" }}>
                <select
                  value={devStatus}
                  onChange={(e) => setDevStatus(e.target.value as "ONLINE" | "OFFLINE" | "DEGRADED")}
                  style={{ flex: 1 }}
                >
                  <option value="ONLINE">ONLINE</option>
                  <option value="OFFLINE">OFFLINE</option>
                  <option value="DEGRADED">DEGRADED</option>
                </select>
                <button
                  onClick={handleReportDevStatus}
                  style={{ backgroundColor: "#475569", color: "white", border: "none" }}
                >
                  Report Status
                </button>
              </div>

              <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
                <input
                  type="text"
                  value={ackCmdId}
                  onChange={(e) => setAckCmdId(e.target.value)}
                  placeholder="Command ID"
                  style={{ flex: 1 }}
                />
                <select
                  value={ackStatus}
                  onChange={(e) => setAckStatus(e.target.value as "ACK" | "NACK")}
                  style={{ width: "80px" }}
                >
                  <option value="ACK">ACK</option>
                  <option value="NACK">NACK</option>
                </select>
              </div>
              <button
                onClick={handleSendAck}
                style={{ backgroundColor: "#6d28d9", color: "white", border: "none" }}
              >
                Inject ACK/NACK
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
