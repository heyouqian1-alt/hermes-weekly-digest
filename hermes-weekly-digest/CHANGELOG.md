# CHANGELOG

All notable changes to this project will be documented in this file.

## [v1.0.0] - 2026-07-03

### Added
- 初始发布
- 跨 Hermes Agent 周报自动收集（SQLite 直读）
- 经典报纸风格 PDF 生成（亚麻纸纹理 + 报头 + 表格交替色）
- 自动版本号递增机制
- cron 守护调度系统（每 4 小时检测周一）
- 完整文档：安装指南、架构说明、工作流程

### Changed
- PDF 引擎精简为单一经典报纸风格（423 行）

### Fixed
- requirements.txt 移除未使用的 requests 依赖
- LICENSE 作者信息替换
- .gitignore 添加测试产物过滤
