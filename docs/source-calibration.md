# Live source calibration

The source owns calibration geometry, profile storage, and its persistent editor.
The shared bridge presents one **Calibrate** button. It opens the advertised
`calibration_editor.url` and proxies a bounded, acknowledged `begin` request via
`/teleop/source/calibrate` to local ZMQ REP. It never reads profiles or performs
calibration math. The browser/editor communicates directly with the source.

Begin sets `calibration_valid=false` and closes the gate. The backend retains its
scene, cameras, and recording transaction, but omits control samples while gated.
In the editor, **Finish Calibration** validates, saves, and applies the profile.
The page stays alive without pose updates. A B pause/resume cycle is required
before motion resumes. Cancel keeps the previous profile with the same B guard.
There is no second direction-alignment flow in the controls extension.

`calibration_revision` changes at mode boundaries. The Cartesian guard re-anchors
on a new revision even if its invalidation packet was dropped. Controller trails
also reset, preventing lines between incompatible coordinates. The source, not
the bridge, owns invalidation policy; native safety remains with the backend.

Recordings omit paused/calibrating frames. Per-step source metadata retains the
effective axes and saved file digest; episode provenance summarizes
`effective_calibrations` by digest. A take crossing different profile digests is
preserved but marked `mixed_calibration` and is not automatically training
eligible. Save the previous take before recalibrating, then start a new one for
clean provenance. Cancel/re-enter alone does not change the saved digest.

Keep unauthenticated source RPC and editor HTTP bound to a trusted host. A remote
operator must be able to reach the advertised editor URL, e.g. by forwarding its
port alongside the observation bridge. Popup-blocking clients expose a fallback
link; the source session stays safely gated until Finish or Cancel and B.
