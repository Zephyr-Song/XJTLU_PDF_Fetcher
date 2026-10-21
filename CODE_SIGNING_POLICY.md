# Code Signing Policy

Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

## Scope

Every Windows binary distributed by this project (`XJTLU_PDF_Fetcher.exe`) is Authenticode-signed during the GitHub Actions release pipeline. Binaries published before the first signed release are unsigned.

## Build provenance

All release artifacts are produced by the GitHub Actions workflow `.github/workflows/build-release.yml` in this public repository, from the source tree of the corresponding release tag. Manually uploaded binaries are not accepted.

## Team roles

| Role | Person |
|---|---|
| Author / Committer | [@Zephyr-Song](https://github.com/Zephyr-Song) |
| Reviewer | [@Zephyr-Song](https://github.com/Zephyr-Song) |
| Approver (signing approval for each release) | [@Zephyr-Song](https://github.com/Zephyr-Song) |

This is a single-maintainer project; all three roles are held by the repository owner.

## Account security

All accounts interacting with the signing pipeline (SignPath and source code repository access) use multi-factor authentication.

## Approval

Each release requires one manual approval of the signing request by the Approver in the SignPath portal, before the signed artifact is published.

## Privacy

This program does not transfer any information about the user or the system to any other networked system. Its only network requests are the ETD pages you visit and the exam paper files you download yourself.

---

## 分发边界（中文说明）

本工具仅供**个人离线复习**使用：把你本人有权限访问的试卷保存到本地。

**不允许**分发、上传、分享试卷（包括群聊、网盘、社交平台），也不允许任何商业用途。试卷版权归学校与出题教师所有。详见 [README](README.md) 的「使用须知」章节。
