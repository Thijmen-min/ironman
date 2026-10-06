# HealthWatcher coaching method

How the coach plans and adapts training. The coach reads this before building or revising a plan.
It combines what adaptive platforms do (TrainerRoad, TriDot, HumanGO, TrainingPeaks' Annual Training
Plan, Garmin daily suggestions) with current evidence (sources at the bottom).

## 1. Three planning horizons

| Horizon | What exists | Detail | Changes when |
|---|---|---|---|
| **Season** (to the A-race) | Phases (Prep, Base, Build, Peak, Taper, Race) from the Profile, plus one `plan_weeks` row per week | **Outline only**: phase, week type, hours, TSS, one-line focus. No session specifics beyond the current block | Goal/date changes, illness or injury, or a test shows a big jump or drop |
| **Block** (3-4 weeks) | Weeks grouped as load, load, (load), recovery/test | Weekly hours/TSS, per-sport split, 2-3 key-session *types* per week | At each block boundary, from that block's data |
| **Detail** (next 1-2 weeks, max 4) | Real workouts on the calendar (`add_planned_workouts`) | Full session: purpose, warm-up / main set / cool-down, targets from current thresholds, TSS estimate | At every weekly review, and immediately when readiness says so |

Never detail sessions more than 4 weeks out. Nobody knows how January will go in October, so the
outline gives direction and the detail follows the athlete.

## 2. Blocks, recovery and testing

- **Load pattern:** 3:1 (three load weeks, one recovery week) by default; 2:1 when recovery markers are
  poor, life stress is high, or volume is close to the athlete's ceiling. Recovery weeks are about 60-70 %
  of load-week volume and keep a little intensity.
- **Ramp:** CTL rises about 3-6 TSS/day per week in base and build; above 8 for more than a week is a red
  flag. Load weeks within a block step up about 5-10 %.
- **Tests at the end of every 2nd block (every 6-8 weeks), in the recovery week, when fresh:**
  - Bike: FTP test. Use **the same protocol every time** (20-min TT x 0.95 on the indoor power trainer;
    ramp tests are repeatable but overestimate for diesel types). Outdoors without power, an LTHR test
    (30-min TT, average HR of the last 20 min).
  - Swim: CSS test (400 m + 200 m TT), every 4-6 weeks if possible (it's cheap).
  - Run: a 30-min TT for LTHR and pace, **only after medical clearance and once run volume is ≥ 50-60 %
    of normal**. Until then, no run tests.
- After a test, write the new thresholds with `update_profile`, giving the reason. Zones and TSS
  follow automatically. Mark tests on the calendar with `kind: "test"`.

## 3. Intensity distribution

- About 75-80 % of training time in Z1-Z2 (check the `hr_z*` sums weekly).
- **Base:** pyramidal (lots of Z2, some tempo/sweet spot, little VO2). Recent meta-analyses find
  polarized only marginally better for elite athletes, and pyramidal equal or better for recreational
  athletes, with large individual differences. Start pyramidal; let the data decide.
- **Build/Peak:** shift toward race specificity. For an Ironman that means long Z2 with IM-pace
  blocks (bike about 68-78 % FTP), bricks, and some threshold or VO2 work for ceiling, polarized-leaning.
- At most 2-3 quality sessions a week, never on consecutive days unless planned as a block.
  Double-threshold days (Norwegian style) only with lactate control and a large aerobic base; not for
  this athlete's first Ironman season.

## 4. Durability (the "fourth dimension" of endurance)

Ironman performance depends on how well power, pace and efficiency hold up after hours of work, not
just fresh thresholds.
- Grow the long ride and long run (separately) through base and build. Place controlled efforts
  late in long sessions (e.g. the last 45-60 min of a long ride at IM pace).
- Bricks: short run off the bike from Build onward (knee permitting).
- **Strength 2x/week** (heavy, low reps, plus plyometrics when cleared) through Base and Build; 1x
  maintenance in Peak; none in the taper week. This improves economy and durability without
  hurting endurance.

## 5. Daily and weekly adaptation (the "adaptive" part)

Inputs: planned vs done (compliance), CTL/ATL/TSB and ramp, HRV vs baseline, resting HR vs 30-day mean,
sleep, Garmin readiness and Body Battery, subjective check-ins, and session RPE where given.

**Daily (readiness verdict):**
- Green (Go/Train): do the session as planned.
- Amber (one or two warnings): keep the duration, drop the intensity one zone, or swap with an easy day.
- Red (illness, injury, HRV below baseline for 2+ days with RHR +5 or more, TSB < -30): rest or recovery
  session only.

HRV-guided adjustment gives small but consistent benefits and fewer non-responders, so honour it.
Treat ACWR as a descriptive signal only; it doesn't predict injury on its own.

**Weekly review (every Sunday/Monday):**
1. Compliance: planned vs done (sessions, hours, TSS); which key sessions were hit or missed and why.
2. Response: HRV/RHR/sleep trend, TSB, check-ins, any pain.
3. Decide: progress as planned, repeat the week, or pull the recovery week forward.
4. Detail the next 1-2 weeks; adjust the block targets only if needed. Don't punish missed sessions by
   cramming; move on.

## 6. Fuelling (trainable, race-critical)

- Long sessions over 2 h from Build: practise race fuelling. Progress from about 60 g/h towards
  90 g/h (multiple transportable carbohydrates; ~120 g/h only if well tolerated after gut training).
  Log tolerance in the check-in notes.
- Race-pace sessions are also fuelling rehearsals: same products, timing and fluid/sodium plan.

## 7. Taper

- 2-3 weeks for a full Ironman. Reduce volume progressively by about 40-60 %, **keep intensity and
  frequency**. Taper effects are bigger after a planned overload block before the taper.
- Race week: short openers, rest the day before or day -2, logistics.

## 8. Health guardrails

- Profile limitations override everything. Current: right knee after ACL reconstruction. Running only
  after physio clearance, then walk-run for 3-4 weeks; no intensity or hills until run volume is back
  to 50-60 % of normal; assess knee response the next morning. Bike and swim carry the aerobic load
  until then.
- Pain that changes movement, chest pain, fainting or palpitations, or fever with a raised RHR means
  stop and refer.

## Sources

The full reading list is in `research/SOURCES.md`.

- Silva Oliveira et al. 2024, polarized vs other TID meta-analysis: https://link.springer.com/article/10.1007/s40279-024-02034-z
- 2025 TID findings (pyramidal then polarized; responder clusters): https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2025.1657892/full , https://www.nature.com/articles/s41598-025-25369-7
- HRV-guided training meta-analyses: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8507742/ , https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7663087/
- Durability as a determinant of endurance performance: https://openrepository.aut.ac.nz/items/e4ed557d-8c56-44ba-9eac-520fc0ae1aae/full
- Tapering meta-analysis (endurance, 2023): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10171681/
- ACWR critique: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8138569/
- High carbohydrate intake (90 vs 120 g/h): https://www.slowtwitch.com/news/how-high-is-high-carb-fueling/
- Return to run after ACLR: https://journal.aspetar.com/en/journals/volume-12-targeted-topic-rehabilitation-after-acl-injury/the-latest-guidance-on-return-to-run-after-acl-reconstruction
- Threshold tests (swim/bike/run): https://www.trainingpeaks.com/learn/articles/threshold-tests-for-swim-bike-and-run
- Adaptive platforms: https://www.trainerroad.com/blog/progression-levels-what-they-are-and-how-to-use-them/ , https://www.tridot.com/what-tridot-delivers , https://challengefamily.com/news/humango-training-that-adapts-to-life-not-the-other-way-around/
- Norwegian method overview: https://trainingpeaks.com/coach-blog/norwegian-training-method-world-champion-triathletes
