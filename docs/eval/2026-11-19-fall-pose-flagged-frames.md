<!-- The frozen package (the 36 JPEGs, raw per-frame JSON, contact sheets)
     is at /mnt/storage/ruth-models/eval/2026-11-19-fall-pose-flagged/ and
     is deliberately not in the repo. This file is the index. -->

# fall_pose: the 36 HPCL frames where only the new model fired

**Use:** the non-fall set for fall calibration (BL-1). Every frame here is a
false alarm: the history contains no real falls.

**Where they come from.** The 2026-11-19 parity replay
(`docs/model-store/FALL_POSE_MIGRATION.md`) ran 415 random HPCL evidence
frames through the built-in model and through `fall_pose`, with the same
rule in both. These are the 36 frames where the built-in recorded nothing
and `fall_pose` recorded a fall: 22 `possible_fall` and 14 `fall_detected`.
- In 33 of the 36, `fall_pose` found more people than the built-in.
- They include the frames where wall-mounted CCTV cameras were detected
  as people (rows 2 and 3, camera 75080).

**Columns:**
- **Time:** when the frame was captured (IST). The frames were saved as
  evidence for PPE violations, not fall violations.
- **Persons:** persons found by the built-in → by `fall_pose`.
- **Firing boxes:** each box the rule fired on, as person-detection
  confidence / box height as a fraction of the frame.
- **Floor 0.5:** "yes" means a `min_person_confidence` of 0.5 removes
  every firing box in that frame.

**Floor 0.5 removes 6 of the 36.** Checked by eye:
- Rows 2 and 3 are wall-mounted cameras.
- Row 11 is an equipment box, row 29 a railing, row 6 bags.
- Row 31 looks down into a vessel. Its boxes (0.26–0.38) sit on very
  small, distant shapes that may include workers far below. So the floor
  also removes genuinely tiny people.

**Deployed floor: 0.45** (2026-11-19). It removes the same frames except
row 3: its higher box is at 0.49, so that wall-mounted-camera frame still
fires.

The other 30 are confidently detected workers, standing or bending. Only
the size-relative geometry and the other BL-1 candidates can address them.

Package contents:
- `frames/<uuid>.jpg`: the 36 frames.
- `flagged36.json`: per frame, every firing box (bbox in frame pixels,
  confidence, height fraction), person counts and the floor-0.5 flag.
- `dropped05.jpg`: the 6 frames the floor removes, boxes drawn.
- `today_sheet.jpg`: the 10 demo-camera `fall_pose` violations of
  2026-11-19 (3 real staged falls and 7 empty-room false alarms), for the
  floor proposal.

| # | Camera | Time (IST) | Evidence frame (`/mnt/storage/ruth-evidence/frames/…`) | fall_pose | Persons | Firing boxes (conf / height) | Floor 0.5 |
|---|---|---|---|---|---|---|---|
| 1 | 75080 | 2026-10-19 22:03:43 | `2026/10/19/16786d5e-3674-4198-acd6-cca27927fab1.jpg` | fall_detected | 1 → 2 | 0.70 / 0.34 |  |
| 2 | 75080 | 2026-10-20 17:03:58 | `2026/10/20/9df77d6c-222b-4882-8783-3aff71dd4737.jpg` | fall_detected | 0 → 2 | 0.42 / 0.09 | yes |
| 3 | 75080 | 2026-10-22 16:06:14 | `2026/10/22/28902253-643c-4e9d-ba88-937788b8036b.jpg` | fall_detected | 0 → 3 | 0.49 / 0.12; 0.36 / 0.11 | yes |
| 4 | 75080 | 2026-10-22 16:18:41 | `2026/10/22/6604abc4-6842-4ad7-8cac-df4d33c5b663.jpg` | fall_detected | 0 → 2 | 0.51 / 0.12 |  |
| 5 | 75080 | 2026-11-02 04:17:47 | `2026/11/01/651a8116-bf0e-440d-9e89-e767dc9289a4.jpg` | possible_fall | 1 → 3 | 0.69 / 0.35 |  |
| 6 | 75080 | 2026-11-02 16:47:19 | `2026/11/02/abf8a909-3afb-4194-9d3c-32de6e8a173c.jpg` | possible_fall | 1 → 2 | 0.34 / 0.30 | yes |
| 7 | 75081 | 2026-10-20 10:02:51 | `2026/10/20/9b06f2f3-ec4b-4192-a32b-3064488350f4.jpg` | fall_detected | 1 → 2 | 0.50 / 0.16 |  |
| 8 | 75081 | 2026-10-20 16:09:54 | `2026/10/20/6a86f911-bced-4f4f-8f86-b29d4c384fe7.jpg` | fall_detected | 5 → 4 | 0.79 / 0.17 |  |
| 9 | 75081 | 2026-10-24 20:28:58 | `2026/10/24/e3ecc89a-668b-4c30-9590-551eb1737df0.jpg` | possible_fall | 2 → 3 | 0.50 / 0.12 |  |
| 10 | 75084 | 2026-10-22 19:27:57 | `2026/10/22/ade6e615-da2d-480c-bac8-26b2ea4a7ea1.jpg` | possible_fall | 1 → 2 | 0.67 / 0.21 |  |
| 11 | 75088 | 2026-10-25 10:11:30 | `2026/10/25/0c11d11f-20b7-43fc-bc07-41557bd70b77.jpg` | possible_fall | 1 → 2 | 0.25 / 0.28 | yes |
| 12 | 75096 | 2026-10-30 14:52:00 | `2026/10/30/b3e9dc9c-1c07-43be-9925-854a6df2d524.jpg` | fall_detected | 1 → 3 | 0.89 / 0.41; 0.83 / 0.16 |  |
| 13 | 75096 | 2026-10-30 15:09:34 | `2026/10/30/ec5faafc-7d22-423d-bdde-25bf2c7d0653.jpg` | fall_detected | 1 → 4 | 0.90 / 0.21; 0.90 / 0.23 |  |
| 14 | 75096 | 2026-10-30 17:04:47 | `2026/10/30/3210569a-984a-4ffb-bdd0-62c9471ea5b9.jpg` | fall_detected | 2 → 5 | 0.72 / 0.21; 0.50 / 0.28; 0.33 / 0.33 |  |
| 15 | 75096 | 2026-10-31 17:19:25 | `2026/10/31/55843413-fb56-4132-a192-b96cd908edc3.jpg` | fall_detected | 3 → 3 | 0.88 / 0.48 |  |
| 16 | 75096 | 2026-11-04 13:39:05 | `2026/11/04/4ee04910-21a5-4a80-97a2-c9d0d4c78035.jpg` | fall_detected | 1 → 2 | 0.84 / 0.48 |  |
| 17 | 75096 | 2026-11-04 14:20:07 | `2026/11/04/84c7e1db-e097-439c-a956-596d6bff7215.jpg` | possible_fall | 1 → 3 | 0.75 / 0.35 |  |
| 18 | 75098 | 2026-10-21 11:39:51 | `2026/10/21/36597e19-d69f-4c5e-8260-b3558d4ba692.jpg` | possible_fall | 2 → 2 | 0.78 / 0.27 |  |
| 19 | 75098 | 2026-10-24 16:25:40 | `2026/10/24/ba446263-866e-4da4-ae67-c8f034af5f69.jpg` | possible_fall | 1 → 3 | 0.87 / 0.30 |  |
| 20 | 75098 | 2026-10-24 17:02:19 | `2026/10/24/a377f3cd-8960-4b5e-97e9-c9b30294cc57.jpg` | possible_fall | 4 → 5 | 0.89 / 0.25 |  |
| 21 | 75098 | 2026-10-24 17:59:07 | `2026/10/24/79895235-d1ab-4d53-b5f8-4d1a6047eeb2.jpg` | possible_fall | 2 → 4 | 0.85 / 0.32; 0.70 / 0.25 |  |
| 22 | 75098 | 2026-10-25 10:50:38 | `2026/10/25/59db2885-cc1f-4d6d-8728-a9fe6031e97a.jpg` | possible_fall | 1 → 2 | 0.53 / 0.21 |  |
| 23 | 75098 | 2026-10-25 14:55:47 | `2026/10/25/0cf2336e-0eda-41f1-82df-b19a6d5f4974.jpg` | possible_fall | 3 → 5 | 0.89 / 0.28; 0.30 / 0.25 |  |
| 24 | 75098 | 2026-10-26 06:36:13 | `2026/10/26/fc4e35c5-6671-4485-aed1-a8470928a714.jpg` | possible_fall | 4 → 6 | 0.76 / 0.19 |  |
| 25 | 75098 | 2026-10-26 17:53:48 | `2026/10/26/9586d11c-108a-4d25-8b22-0b08c734cbd6.jpg` | possible_fall | 0 → 4 | 0.51 / 0.17; 0.48 / 0.25; 0.35 / 0.15 |  |
| 26 | 75098 | 2026-10-27 09:41:24 | `2026/10/27/24f5353c-6a51-4971-8401-21f8da3d0613.jpg` | possible_fall | 4 → 5 | 0.90 / 0.32 |  |
| 27 | 75098 | 2026-10-27 09:54:03 | `2026/10/27/4e404dff-2f5b-48ba-bac1-b0db44778786.jpg` | possible_fall | 3 → 6 | 0.93 / 0.34 |  |
| 28 | 75098 | 2026-11-02 17:11:48 | `2026/11/02/8842ee89-376e-411c-af47-4609edb36c6f.jpg` | possible_fall | 5 → 6 | 0.89 / 0.25 |  |
| 29 | 75098 | 2026-11-04 17:40:01 | `2026/11/04/bba57934-2059-409e-a9ef-e38e1ef6342c.jpg` | possible_fall | 1 → 3 | 0.43 / 0.28 | yes |
| 30 | 75106 | 2026-10-29 15:45:36 | `2026/10/29/fa7471f6-2d6a-4f92-aa1b-c4d2bcb30840.jpg` | possible_fall | 0 → 1 | 0.54 / 0.85 |  |
| 31 | 75106 | 2026-10-30 23:48:30 | `2026/10/30/01b5778c-1e81-4f92-808e-88f78c49eaa3.jpg` | fall_detected | 0 → 3 | 0.38 / 0.14; 0.27 / 0.39; 0.26 / 0.15 | yes |
| 32 | 75129 | 2026-10-31 12:15:25 | `2026/10/31/c5ac9ae7-4b78-4295-9c5f-813ff249ea7f.jpg` | possible_fall | 2 → 6 | 0.78 / 0.31 |  |
| 33 | 75129 | 2026-10-31 15:33:37 | `2026/10/31/268c4dc6-bf73-467e-9d6b-f84a24db25d8.jpg` | possible_fall | 2 → 5 | 0.84 / 0.22 |  |
| 34 | 75129 | 2026-10-31 16:41:51 | `2026/10/31/f4221194-8cb1-4381-ae45-d6fda95bf174.jpg` | possible_fall | 6 → 7 | 0.80 / 0.23 |  |
| 35 | 75129 | 2026-10-31 17:40:20 | `2026/10/31/440b8380-ac79-4f68-a5e5-e622d9dfc38b.jpg` | fall_detected | 4 → 5 | 0.92 / 0.55 |  |
| 36 | 75129 | 2026-11-02 09:49:13 | `2026/11/02/25b6becc-8b80-4dc9-b71c-1ae62179d87f.jpg` | fall_detected | 0 → 2 | 0.76 / 0.46 |  |
