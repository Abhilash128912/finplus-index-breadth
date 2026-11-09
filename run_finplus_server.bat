@echo off
title FinPlus+ Index Breadth & BTST Engine Daemon
echo ========================================================
echo   Starting FinPlus+ Index Breadth & BTST Engine
echo   Port: http://127.0.0.1:8000
echo   Live Cloud: https://finplus-index-breadth.onrender.com
echo   NTFY: https://ntfy.sh/Finplus-Delta
echo ========================================================
cd /d "D:\AI_APPS"
python -m uvicorn finplus_index_breadth.src.api.server:app --host 127.0.0.1 --port 8000 --reload
pause

