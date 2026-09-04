# Changelog

## 1.3.3

- Show `Record Arm 1` and `Continue to Arm 2` for sequential single-controller
  dual-arm acquisition while keeping the compact acknowledged-button surface.
- Allow Save to wait for a backend's transactional simulator reset and expose
  the active arm plus replay progress through the typed operator-state topic.

## 1.3.2

- Remove Foxglove hold/resume controls; the Quest B button is the single owner
  of pause/resume and downstream recorders exclude closed-clutch intervals.

## 1.3.1

- Make repeated CI publication byte-for-byte reproducible.

## 1.3.0

- Reduce the panel to acknowledged control buttons only; connection and source
  health stay in Foxglove Diagnostics.
- Accept the canonical source state while the gateway keeps cached 1.1 clients
  working during desktop extension refresh.

## 1.2.0

- Move canonical teleoperation presentation ownership into `embodied-ops`.
- Keep the existing organization layout and acknowledged control contract.

## 1.1.0

- Show live Quest, controller, backend, camera-latency, and recording state in
  the same compact panel as the acknowledged controls.
- Disable commands when the WebSocket state heartbeat is stale and make
  recording actions reflect the backend state.

## 1.0.5

- Arrange the camera panels side by side at a near-native aspect ratio.
- Move force and torque plots below the cameras and keep diagnostics and
  controls in a dedicated operator sidebar.
- Simplify the controls into compact Robot, Episode, and Recording rows.

## 1.0.4

- Publish the compact ForceVLA force and torque plot layout alongside the
  existing acknowledged React controls.

## 1.0.3

- Treat a command as successful only when the backend returns both
  `accepted=true` and `applied=true`.
- Serialize service requests, confirm destructive discard, and clarify compact
  operator feedback.
- Refresh compatible build tooling and keep all dependencies pinned.

## 1.0.2

- Add the compact Safety, Episode, and Recording control groups.
- Surface backend acknowledgement and errors without a raw JSON panel.
- Disable concurrent commands while a request is in flight.
