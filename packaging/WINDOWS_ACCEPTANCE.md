# Windows correction acceptance record — PENDING

Application: 0.2.0 repaired review candidate. Primary release platform: Windows x64.
Available compatibility test: Horizon Windows 10 Enterprise 19045 x64, 16 GB,
approximately 108–110 GB free, NVIDIA A16-1Q/VMware graphics. The user reported a
plain-Slicer OpenGL 3.2 rendering probe; this is not installed-annotator acceptance.
The historical installer at `6a562ef` passed hosted lifecycle/import checks but
predates the current correction adapter. **A refreshed installed correction
workflow has not passed Windows acceptance. Windows 11 remains untested.**
Do not mark a row passed without executing it on the installed application.
Use synthetic input unless development/practice access is explicitly permitted.
Attach hashes, test logs and screenshots outside the repository if they contain real data.

| Check | Evidence / result |
|---|---|
| OS edition/build, CPU, RAM, graphics/driver, monitor resolution | Pending |
| Installer filename and SHA256; source commit/build receipt | Pending |
| Clean standard-user installation; expected Start-menu launch | Pending |
| Offline application operation with bundled dependencies; retain Horizon connection and test app-only network restriction if permitted | Pending |
| Open synthetic dataset; first-use local work location | Pending |
| Explicit reader assignment; two readers use separate work folders and attribution | Pending |
| Offline reader guide opens locally; no terminal or external Python setup required | Pending |
| Installed source commit and file fingerprint match the frozen build, not just version 0.2.0 | Pending |
| Installed headless technical correction/save/reopen/export, distinct from GUI acceptance | Pending current build receipt |
| Flat correction package automatically loads exact permitted masks and explicit practice actor | Pending |
| Missing/invalid/blocked masks refuse correction without silent blank labels | Pending |
| Native oblique acquired-plane stroke: only intended K slice changed | Pending |
| Axis aligned and oblique geometry retained after save/reopen | Pending |
| Paint, Draw, Erase; label switch; undo/redo; fixed mapping 1/2 | Pending |
| Mouse wheel, previous/next, typed notes do not trigger shortcuts | Pending |
| Zoom/pan/window-level/reset, orientation labels, segmentation visibility | Pending |
| Review empty slices; edits invalidate review on affected slices | Pending |
| Autosave; close/reopen; forced termination/recovery | Pending |
| Two processes: second writer blocked, original work intact | Pending |
| Disk-full, denied path, corrupt latest checkpoint: clear recovery | Pending |
| Existing approval preserved; subsequent edits create a draft | Pending |
| Prediction-free job cannot load hidden/nearby predictions | Pending |
| Reconnect moved dataset; wrong hash rejected | Pending |
| Approve deliberately; only eligible cases exported | Pending |
| Visible Export and Cancel buttons work with real mouse/keyboard input | Pending |
| Native export folder picker, cancellation and completion notice work offline | Pending |
| Installed correction automation plus fresh-process restore on both procedural geometries | Pending |
| Two separately permitted real-case copies, including oblique, complete correction/save/restart/export | Pending; private evidence only, after synthetic checks |
| ZIP reopen with independent reader; full grid/hashes/review records match | Pending |
| ASCII installation path with spaces; Unicode install path clearly rejected; dataset/work Unicode and maximum paths | Pending |
| Smaller logical work areas, including 960×540; native Windows 100/125/150/175/200% scaling | Pending; Mac Qt simulations do not establish Windows DPI behavior |
| Uninstall/reinstall retains work outside installation directory | Pending |
| Transitive licenses and bundled nibabel/typing_extensions notices present | Pending |
| Downstream training-loader integration | Separate integration, unavailable |

Technical checks establish identity and file consistency; they do not establish
anatomical correctness or an independent second-reader assessment.
