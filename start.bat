@echo off
chcp 65001 > nul
echo.
echo ============================================
echo  防災訓練認定試験 採点システム
echo  起動中...
echo ============================================
echo.

:: Check for ANTHROPIC_API_KEY
if "%ANTHROPIC_API_KEY%"=="" (
  echo [エラー] 環境変数 ANTHROPIC_API_KEY が設定されていません。
  echo.
  echo 設定方法:
  echo   set ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
  echo.
  pause
  exit /b 1
)

:: Install dependencies if needed
pip show flask >nul 2>&1
if errorlevel 1 (
  echo 依存ライブラリをインストールしています...
  pip install -r requirements.txt
  echo.
)

:: Generate sample files
python create_samples.py

echo.
echo ブラウザで以下のURLを開いてください:
echo   http://localhost:5050
echo.
echo 終了するには Ctrl+C を押してください。
echo.
python app.py
