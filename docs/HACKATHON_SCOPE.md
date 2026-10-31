Pit Wall: Hackathon Scope
Based on PROCESS_FLOW.md status as of 2026-10-28 (commit e426bb3). Event time: 8 to 12 hours. Team builds with Claude Code (Max plan), so time estimates below are agent-assisted and include review and testing, not only writing code.

Items marked Elevated were raised above the previous version of this plan. Each one says what changed.

1. The idea in short
Problem. In 2026 F1, races are decided by battery energy. Each team knows its own battery but cannot see its rivals'. Real race engineers make calls (attack, defend, save, pit) from public timing and their own estimates. No game or tool lets you practise that job: they either show you everything or nothing.

Solution. You are the race engineer of one car. You see your car in full and rivals only through a noisy public feed and a radar estimate of their battery. You talk to your driver on the radio, the AI driver carries out your calls, and the race reacts with rival strategies, Safety Cars and pit windows. After the flag, the true rival battery levels are revealed and every call you made gets a cost in seconds.

What the demo must show:

The hidden information (rival battery shown as an estimate with confidence).
Making real pit wall calls under pressure (radio, alerts, Safety Car, pit window).
The reveal after the race (estimate vs truth, and what each call cost or gained).
2. Already built (we demo this as is)
Part	Flow	Notes
Suzuka track	PF-01	Only track. Enough for a demo.
Race simulation	PF-04	Full 22-car race runs headless in about 7 s.
Clock, Pause, 1x, 4x, 16x	PF-05	30 Hz frames, no skipped steps.
Information barrier and radar estimate	PF-06	Tested. This is the core idea.
Button commands with radio delay	PF-07	Energy modes, BOX, DEFEND, ATTACK, HOLD.
Alerts and F1/F2/F3 calls	Sprint	ATTACK, DEFEND, re-pass and closing-speed alerts.
Rival strategy AI (dry, green flag)	PF-10	Rivals battle, change modes and pit on their own.
Overtakes and pit stops	PF-11, PF-12	Full pit state machine.
Call summary at the flag	Sprint	Lists each alert, the option chosen and the result.
Snapshot, fork and paired-seed outcomes	MVP-06, call_outcome.py	Base for the decision cost and the strategy panel.
Weather model	PF-14	Works in the engine, not shown in the UI.
Test mode, presets, replay viewer	Sprint	Useful for rehearsing the demo.
3. Core hackathon features
Picked because each one completes the story and builds on code that already exists. Times are agent-assisted.

#	Feature	Why it was picked	Builds on	Time
H1	Post-race Reveal and decision cost	The payoff of the idea. Judges see what was hidden and what each call was worth.	Call summary, snapshots, call_outcome.py	2.5 h
H2	Team radio: talk to your driver	The live-demo hook. Feels like a real pit wall.	Command validation and queue	2.5 h
H3	Driver radio replies with voice	F1 fans know team radio. Hearing the driver makes the demo memorable.	Radio log, alerts	2 h
H4	Safety Car and VSC	The biggest strategy moment in real F1. Every F1 fan knows the "cheap pit stop" call.	Driver mistakes and retirements (inputs exist)	3 h
H5	Strategy panel: pit window and undercut	Shows the engineer's tool of choice. Uses data taken only from radar estimates, so it respects the barrier.	Snapshot and fork	2.5 h
H6	Pit wall UI upgrade	Makes the screen look like a real pit wall, not a prototype.	Lite UI	2 h
H7	Realism pass	F1 judges will spot unrealistic numbers.	Overtake model, configs	1.5 h
H8	Demo setup and rehearsal	One reliable, rehearsed race.	Presets, replay viewer	1.5 h
Total	About 17.5 person-hours, so about 6 h each for a team of 3, plus integration		
H1. Post-race Reveal and decision cost
At the flag, add a Reveal screen to the call summary.
For the rivals you raced most, plot true battery against your radar estimate and its confidence band, per lap.
Mark each call on the timeline with position and gap before and 2 laps after.
Show radar error (MAE in MJ) and how many calls were made on an estimate that was off by more than 1 MJ.
Elevated: each call now gets a cost in seconds. At every call, fork the race from the snapshot, run the main other options with paired seeds (true data is allowed after the flag), and show "your call: +1.8 s vs best option". This is a light version of the PF-16 debrief, using the existing call_outcome.py.
H2. Team radio: talk to your driver
Text box in the radio panel. Commands go through the existing validation and queue, so rejections and acks already work.
Keyword parser first, so it works offline: save/harvest, push/attack, overtake, defend, box + compound + lap, cancel box.
Elevated: a hosted LLM with function calling sits on top of the keyword parser and handles free phrasing ("hold him off till the hairpin then go for it into 130R"). Timeout 2 s, then keyword parser, then "Say again?".
Elevated: push-to-talk voice input with local speech-to-text (for example faster-whisper). Typing stays available as the fallback for a noisy venue.
Note: the Claude Max plan covers Claude Code only. The app's LLM calls need their own API key, or a small local model.
H3. Driver radio replies with voice
Unprompted triggers: battery under 0.5 MJ before a long straight, tyre wear over 70%, position gained or lost, Safety Car or VSC deployed.
Rate limit: at most 1 message per 20 s of sim time.
Elevated: replies are written by the LLM from Our Car data only, checked against the facts and capped at 20 words. Templates are the fallback.
Elevated: text-to-speech with a team-radio filter (band-pass and a light crackle). Muted by default, with a toggle for the demo.
H4. Safety Car and VSC
Elevated: this was left out before. It is now core, because F1 judges will look for it.
Simplified T-038: a driver crash stopped off the racing line brings a VSC; one stopped on the line brings a Safety Car. Values set by hand for the demo, not calibrated.
VSC: speed cap, no overtakes. Safety Car: the field bunches up, no overtakes, restart after a set number of laps.
Cheaper pit stop under SC and VSC (MVP-13).
Rivals get the SC/VSC pit branch (part of T-062), so some box and some stay out.
Banner in the UI plus a driver radio line.
The demo seed also has a scripted SC, so the moment always happens on stage.
H5. Strategy panel: pit window and undercut
Elevated: this was an extra before. It is now core.
Light version of PF-15: candidate plans are stay out, box now, box +1, +2, +3 laps, each with compound options.
8 headless forks per plan over 10 laps, with rival data taken from radar estimates and public tyre info only.
Shows the expected position after the stop for each plan, and undercut or overcut gain on the car ahead.
Runs in a background worker and refreshes each lap or on demand. It must never block the race.
H6. Pit wall UI upgrade
Missing buttons: CANCEL_BOX, PUSH_LAP, MANAGE_TYRES.
"Sim behind" indicator.
Elevated: weather and forecast panel (the model is already done, T-078).
Elevated: SC/VSC banners and track status colours on the timing tower.
Elevated: telemetry traces with a previous-lap ghost (speed, battery, throttle) from T-075.
H7. Realism pass
Elevated: new item. F1-minded judges will check the numbers.
Overtakes are about 75 per race now. Tune zone_difficulty down to a believable number for Suzuka.
Use 2026 terms consistently in the UI and the pitch (for example Overtake mode, not DRS). Check every label against the 2026 regulations before the event.
Run a 15 to 20 lap race. This also avoids the fuel issue (cars run out at lap 41 to 46 with the 70 kg placeholder).
H8. Demo setup and rehearsal
Pick a seed with a battle, an undercut, a Safety Car and one call made on a wrong estimate.
Rehearse 3 times and record a backup video.
4. Left out on purpose
Feature	Why it is out
Calibration race loop (PF-02)	Long compute runs and not visible in a demo. Provisional values are good enough.
Fine-tuned Gemma model (PF-08, R3)	Needs training data, fine-tuning and packaging. A hosted LLM gives the same demo.
Red flag, track limits, penalties (T-102)	Rare in a 15-lap race and not needed for the story.
Full UI_DESIGN window (T-070 to T-074)	The upgraded lite UI is enough.
Other tracks, fictional grid, harvest field	Not needed to show the idea.
5. Extras if the core is done
Independent of each other. Stop at any point.

#	Extra	Why it adds value	Time
E1	Rain race	Force rain at setup, and Rivals box at the crossover (weather branch of T-062). Gives the classic "inters now or one more lap?" call.	2 h
E2	Engineer score	A score out of 100 from the decision costs in H1, as in the PF-16 formula. Easy for judges to compare.	1 h
E3	Real race moment	Start the sim from a real 2026 Suzuka lap using OpenF1 data (light PF-18): "you are on the pit wall at lap 30, what do you do?" Strongest wow for F1 judges, highest risk.	3 h
6. Suggested split (team of 3, each with Claude Code sessions)
Hours	Person A (sim)	Person B (radio and AI)	Person C (UI and demo)
0 to 1	Agree on new data fields (SC state, call costs, radio events)	Same	Same
1 to 4	H4 Safety Car and VSC	H2 team radio	H6 UI upgrade
4 to 7	H5 strategy panel	H3 driver replies and voice	H1 Reveal screen
7 to 8	H1 decision cost forks	Integration	H7 realism pass
8 to 9	Extras if on time	Extras if on time	H8 demo seed
9 to 10+	Freeze, rehearse 3 times, backup video	Same	Slides
Cut line: if the team is behind at hour 6, drop voice input (H2), TTS (H3) and the ghost traces (H6), in that order. The core story still works without them.

7. Fallbacks
If this fails	Use this instead
Hosted LLM	Keyword parser for commands, templates for replies.
Voice input	Typing.
TTS voice	Text in the radio log.
Decision cost forks are slow	Run them in the background after the flag and show a progress bar, or precompute for the demo seed.
Strategy panel is slow	Fewer forks (4) or a shorter horizon (6 laps).
Random SC timing	Scripted SC on the demo seed.
Live UI on stage	Backup video, or the replay viewer on the demo seed.
8. Demo flow (4 minutes)
Setup: Suzuka, Our Car in midfield, 15 laps, demo seed.
Radar panel: "We can't see his battery, we only estimate it."
Push-to-talk: "Save this lap, attack into turn 1 next lap." The driver answers on the radio and does it.
The strategy panel shows the undercut window on the car ahead.
Safety Car. The driver radios it in. We box under the SC, some rivals stay out.
A failed attack: the rival had more energy than we thought.
Reveal: true battery against our estimate, and each call with its cost in seconds.
Close with the roadmap.
9. Roadmap (last slide)
Full calibration against real 2026 races.
On-device Gemma radio.
Full scored debrief with alternatives for every decision.
Replay real 2026 races and make your own calls against the real team.
All 2026 tracks, red flags and penalties.
10. Done checklist
[ ] A 15-lap demo race runs to the flag at 16x with no crash.
[ ] Safety Car or VSC happens on the demo seed, with rival pit decisions.
[ ] Strategy panel updates without slowing the race.
[ ] Reveal shows true vs estimated battery and a cost for each call.
[ ] Radio commands work with no internet (keyword parser).
[ ] Barrier test still passes, including the new strategy panel (no rival truth before the flag outside Test mode).
[ ] Demo rehearsed 3 times and backup video recorded.
11. Notes for the team
Radar error is about 1.44 MJ with a bias of -1.41 MJ. The Reveal will show this. That fits the story, but the owner rule says not to tune the radar on true data, so do not "fix" it for the demo. Be ready to explain it if a judge asks.
Rival HOLD currently means "not attacking" only. The owner should pick HOLD variant A or B before the event.
Faster coding with agents does not speed up testing on stage. Keep the last 1.5 hours for freezing, rehearsing and the backup video.