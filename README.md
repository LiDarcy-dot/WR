# WR — локальный ассистент

Telegram + LM Studio (Qwen) + SQLite на твоём ПК.

## Быстрая установка (одна команда в PowerShell)

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force
irm https://raw.githubusercontent.com/LiDarcy-dot/WR/cursor/local-assistant-scaffold-d6ce/assistant/scripts/install_desktop.ps1 -OutFile $env:TEMP\wr_install.ps1
& $env:TEMP\wr_install.ps1 -BotToken "ТОКЕН_БОТА" -OwnerId ТВОЙ_ID
```

Всё окажется в `Desktop\Assistant`. Запуск: **START_BOT.bat**.

Подробнее: [assistant/SETUP_PC.md](assistant/SETUP_PC.md)
