# PPE Detection Model Weights

## Required Model Files

This directory must contain YOLOv8 model weights for PPE detection. The models are organized into two categories:

### both_classes/ (Presence Detection)
Detects when PPE items ARE present on a person:

| File | Purpose | Size |
|------|---------|------|
| `hardhat.pt` | Hardhat detection | ~40 MB |
| `vest.pt` | Safety vest detection | ~40 MB |
| `goggles.pt` | Safety goggles detection | ~40 MB |
| `gloves.pt` | Work gloves detection | ~40 MB |
| `boots.pt` | Safety boots detection | ~40 MB |
| `person.pt` | Person detection | ~40 MB |

### no_classes/ (Absence/Violation Detection)
Detects when PPE items are MISSING (violation states):

| File | Purpose | Size |
|------|---------|------|
| `no_hardhat.pt` | Missing hardhat detection | ~40 MB |
| `no_vest.pt` | Missing vest detection | ~40 MB |
| `no_goggles.pt` | Missing goggles detection | ~40 MB |
| `no_gloves.pt` | Missing gloves detection | ~40 MB |
| `no_boots.pt` | Missing boots detection | ~40 MB |
| `no_mask.pt` | Missing mask detection | ~40 MB |

## Total Size

Approximately **466 MB** for all 12 model files.

## Installation

Copy the weight files from your existing server:

```bash
# From the source server
scp -r user@source-server:/path/to/ppe-detection-model/weights/* ./weights/

# Or if you have the models stored elsewhere
cp -r /path/to/ppe-weights/* ./weights/
```

## Directory Structure After Setup

```
weights/
├── README.md (this file)
├── both_classes/
│   ├── hardhat.pt
│   ├── vest.pt
│   ├── goggles.pt
│   ├── gloves.pt
│   ├── boots.pt
│   └── person.pt
└── no_classes/
    ├── no_hardhat.pt
    ├── no_vest.pt
    ├── no_goggles.pt
    ├── no_gloves.pt
    ├── no_boots.pt
    └── no_mask.pt
```

## Note

Without these model files, the PPE detection service will fail to start or return errors during inference.
