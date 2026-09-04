# Quest Teleop Controls

A compact React control panel for canonical teleoperation services exposed by
`embodied-teleop-foxglove`.

The panel deliberately contains only two control groups. The Quest B button
owns pause/resume so clutch state cannot diverge between the controller and UI:

- Episode: previous, reset, and next.
- Recording: start, stop and save, and permanently discard the active take.

Every action waits for the backend acknowledgement before another action can be sent. The panel does not bypass the ZMQ command plane or talk directly to ManiSkill/MuJoCo.

## Develop

```sh
npm ci
npm run typecheck
npm run lint
npm run local-install
```

Reload Foxglove after a local install. The registered panel type is `quest-teleop-controls.controls`.

## Package

```sh
npm run package
```

This creates `pengyuerobotics.quest-teleop-controls-<version>.foxe`. Organization publishing is handled by the repository's `publish-foxglove.yml` workflow.
