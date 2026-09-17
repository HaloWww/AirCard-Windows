# AirCard (Windows Port) 🎴

> **Native Windows port of [AirCard](https://github.com/mak5er/AirCard) by [@mak5er](https://github.com/mak5er)**  
> Customizes Apple Wallet & Apple Pay card skins on Windows without jailbreak.  
> **Tested on iOS 17 & 18.**  
> Powered by the `airlift` AirTraffic sync exploit.

---

## About This Port

The original [AirCard](https://github.com/mak5er/AirCard) application was created by **[@mak5er](https://github.com/mak5er)** for macOS (Swift / AppKit).

This repository is an independent Windows port that brings the card skinning engine to Windows. It interfaces directly with official 64-bit Apple Mobile Device DLLs (`AirTrafficHost.dll`, `MobileDevice.dll`, `CoreFoundation.dll`) from iTunes and `pymobiledevice3` to perform the AirTraffic sync escape natively on Windows without needing a Mac.


---

## Requirements
- **Windows 10 / 11 (64-bit)**
- **iTunes for Windows (64-bit)** (Standard installer from Apple, ensuring `Apple Mobile Device Support` is installed).
- **Python 3.10+ (64-bit)**

---

## Installation & Quick Start

1. Clone or download this repository:
   ```cmd
   git clone <repository-url>
   cd AirCard-Windows
   ```
2. Double-click **`run_aircard.bat`** (or run `python main.py`).  
   *On first launch, it will automatically create a virtual environment and install all dependencies.*

---

## How to Customize Apple Wallet Cards

1. Connect your iPhone to your Windows PC via USB cable and ensure it is unlocked and **"Trust this Computer"** is accepted.
2. In AirCard, select **`1`** (Scan Cards).
3. On your iPhone:
   - **Double-click Side (Power) or Home button** to open Apple Pay.
   - Authenticate with **Face ID** / **Touch ID**.
   - **Tap your card** on your screen to trigger instant detection!
4. In AirCard, select **`3`** (Flash Custom Skin to Card).
5. Choose your card and drag & drop your image (PNG / JPG / WebP).
6. Force-close the **Wallet** app on your iPhone from the App Switcher (or lock & reopen) to view your new custom card design!

---

## Credits & Original Author

- **Original macOS Application:** **[@mak5er](https://github.com/mak5er)** ([AirCard Repository](https://github.com/mak5er/AirCard))
- **Contributor:** **[@Lumid-Off](https://github.com/Lumid-Off)**
- **Exploit:** Based on the `airlift` AirTraffic sync escape research.
- **Windows Implementation:** Python + ctypes bridge to official Apple Mobile Device DLLs & `pymobiledevice3`.
