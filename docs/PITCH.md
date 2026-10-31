# We Are Racing, Not Testing

**A pit wall simulator where you guess what you cannot see, make the call, and find out after the race what each call was worth.**

---

## 1. The 30-second version (no F1 knowledge needed)

- From 2026, a Formula 1 car gets **about half its power from a petrol engine and half from an electric battery**.
- The battery is small. A full electric push empties it in **about 11 seconds**. Drivers recharge it while braking.
- **Battery energy now decides races.** If you attack with a full battery against a car with an empty one, you pass it. If you attack when *they* are the one with the full battery, you lose.
- Every team sees **its own** battery exactly. **Nobody can see a rival's battery.**
- The person who decides when to attack, defend, save energy or change tyres is the **race engineer**. They sit at the **pit wall** and talk to the driver over the radio.

**So every race comes down to one question: how much battery does the car in front have right now?**

No game or tool lets you practise that job. Racing games either show you everything or show you nothing. We built the middle ground, which is how real racing works.

---

## 2. The key idea: "clipping"

When a car's battery runs dry on a straight, the electric power cuts out and the car **suddenly stops speeding up**, even though the driver still has the throttle fully open. That is called **clipping**.

Anyone can see clipping in the public speed data. When a rival clips, you have caught a glimpse of their hidden battery.

**Simply Clipping** is our engine that watches every rival's public speed data, spots these moments, and keeps a running estimate of each rival's battery, with an honest score of how sure it is.

---

## 3. What we built: two parts

| Part | In one line | For a non-F1 judge |
| --- | --- | --- |
| **The simulator** (`pitwall_sim`) | A full 22-car race at Suzuka (Japan) under the 2026 rules, running in about 8 seconds | The practice track. It knows the true battery of every car, so we can check our guesses. |
| **Simply Clipping** (`simply_clipping`) | The "radar" that estimates rival batteries from public data only and tells you when to attack or defend | The brain. It never looks at the true answers, and it works on real 2026 race data too. |

The simulator plays two roles. During the race it hides the truth from you, as in real life. After the race it **reveals** the truth and grades you.

---

## 4. How it feels to play

1. **You are the race engineer of one car.** You see your own car perfectly.
2. **Rivals are blurry.** You only see their public timing and a battery *estimate*, shown with how confident it is.
3. **Alerts pop up:** "ATTACK now, he is low on battery", "DEFEND, he is closing fast".
4. **You talk to your driver.** Press a button, or type "save this lap, attack into turn 1 next lap". The driver answers on the radio and does it.
5. **The race reacts:** rivals fight back, a Safety Car comes out, pit stop windows open and close.
6. **At the flag, the reveal:** your guesses next to the true batteries, and every call you made priced in seconds ("your call cost +3.3 s compared with the best option").

---

## 5. All features

✅ works today  ·  🟡 partly built  ·  🔜 planned

### The race

| | Feature | What it means |
| --- | --- | --- |
| ✅ | 2026 power rules | Engine and battery modelled the way the 2026 rules describe them |
| ✅ | Full 22-car race | Every car has its own driver, strategy and battery |
| ✅ | Overtakes and pit stops | Cars battle, pass, change tyres |
| ✅ | Rival AI | Other teams make their own choices: push, save, pit |
| ✅ | Safety Car and Virtual Safety Car | A crash slows the whole field. Pitting then is cheap, the classic big decision. |
| ✅ | Weather model | Rain and forecasts work inside the race |
| ✅ | Pause, 1x, 4x, 16x speed | Watch live, or fast-forward |
| ✅ | Rain race | Pick a lap for rain to start: rivals switch to rain tyres over the next laps, and you make the "now or one more lap?" call |
| ✅ | Crashes in battles | Two cars can touch while overtaking, sometimes bad enough to bring out a Safety Car |
| 🔜 | More tracks | Only Suzuka today |

### Seeing the hidden information

| | Feature | What it means |
| --- | --- | --- |
| ✅ | Information barrier | The rule built into the code: you **never** see a rival's true battery during the race |
| ✅ | Battery radar (Simply Clipping) | Estimates each rival's battery from public speed data, with a confidence score |
| ✅ | Alerts | ATTACK, DEFEND, RE-PASS RISK, CLOSING-SPEED RISK, each with options |
| ✅ | Real race check | Simply Clipping runs on the real 2026 Japanese GP data |

### Talking to the driver

| | Feature | What it means |
| --- | --- | --- |
| ✅ | Command buttons | Push, Save, Attack, Defend, Hold, Box (pit), Cancel box, Push lap, Manage tyres |
| ✅ | Type to the driver | Plain-English radio messages, understood offline with no internet |
| ✅ | Driver talks back | The driver warns you about low battery, worn tyres, places gained or lost, Safety Cars |
| ✅ | Driver voice | Spoken replies with a crackly team-radio filter |
| 🟡 | Smarter radio (AI language model) | Free phrasing like "hold him off till the hairpin, then go for it". Built for OpenAI or Anthropic; switched on once an API key is added. Every AI command is checked before the car obeys it. |
| 🟡 | AI-written driver replies | The driver's lines written by the AI from our own car's data, checked against the facts, 20 words max. Same API key; templates until then. |
| ✅ | Speak instead of type | Hold a key, talk; speech is turned into text on the laptop itself, offline |
| 🔜 | On-device AI radio | A small local AI model, so no internet or API key is needed |

### Strategy and screen

| | Feature | What it means |
| --- | --- | --- |
| ✅ | Strategy panel | Every lap the pit wall compares "stay out" with "pit now / in 1, 2, 3 laps", using only what you are allowed to know |
| ✅ | Pit wall screen | Track map, timing tower, battery radar, alerts, radio log, weather, Safety Car banner |
| ✅ | "Sim behind" warning | If the computer cannot keep up, the race slows down instead of cheating |
| ✅ | Telemetry traces | Speed, throttle and battery around the lap, with last lap shown faintly behind for comparison |

### After the race

| | Feature | What it means |
| --- | --- | --- |
| ✅ | Reveal | Your battery guesses plotted next to the truth |
| ✅ | Cost of every call | Each decision re-run against its alternatives: "+3.3 s compared with the best option" |
| ✅ | Replay viewer | Watch any race back |
| ✅ | Engineer score | One grade out of 100 for your whole race, from the seconds your calls cost |
| 🔜 | Full debrief | Every decision with all its alternatives explained |
| ✅ | Real race moment | Start from the real 2026 Japanese GP at lap 30, with the real order, gaps and tyres: "you are on the pit wall, what do you do?" |
| 🔜 | Replay real races | Make your own calls against what the real team did |

---

## 6. Does it work?

We test Simply Clipping on races it has **never seen** (seeds 6 to 10), against the simulator's simple built-in radar:

| | Built-in radar | **Simply Clipping** |
| --- | --- | --- |
| Battery guess error | 0.84 to 1.28 MJ | **0.36 to 0.88 MJ** |
| "He is clipping" alert correct | 4 to 6 % | **53 to 66 %** |
| Is its confidence honest? (lower is better) | 18 to 34 % off | **4 to 10 % off** |

**On real data (2026 Japanese GP):** it warned twice that Hamilton could re-pass Norris, **15 and 20 seconds before it happened**.

**It is honest about its gaps:** it fires fewer attack alerts than the simple radar, and it missed one real crash because that car's speed data froze. We report these instead of hiding them.

Behind it: **638 automated tests**, and code rules, checked by the tests, that stop the radar from cheating: it may not import the simulator or open the true-answer files.

---

## 7. Why it matters

- **For fans:** finally understand why a driver "suddenly ran out of speed". The 2026 races will be full of it.
- **For learners:** practise real decision-making under uncertainty, then see exactly what each decision cost.
- **For teams and analysts:** Simply Clipping is a plug-in. It runs live on the pit wall, offline on a race file, or on real public data.

The big idea in one sentence: **good decisions are made on good estimates, and this tool shows you both.**

---

## 8. Mini glossary

| Word | Meaning |
| --- | --- |
| Pit wall | Where the team's engineers sit during a race, making the calls |
| Race engineer | The one person who talks to the driver on the radio |
| Clipping | The battery runs out on a straight and the car stops speeding up |
| Harvest / Save | Recharge the battery, a little slower now so you are faster later |
| Attack / Defend | Spend battery to pass a car, or to stop being passed |
| Pit stop / Box | Come into the garage for new tyres ("box, box" on the radio) |
| Safety Car | A crash slows everyone down, so a pit stop costs less time |
| Undercut | Pit before the car ahead, then pass it on fresher tyres |
| MJ (megajoule) | Unit of energy. The battery holds about 4 MJ. |
