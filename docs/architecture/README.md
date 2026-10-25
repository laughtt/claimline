# Architecture diagram

`architecture.html` is the source of `../architecture.png`. The icons in `icons/` are AWS Architecture Icons, taken from the `diagrams` package.

To render it again after editing (Windows, Microsoft Edge):

```powershell
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --headless=new --disable-gpu --hide-scrollbars `
  --user-data-dir="$env:TEMP\edge-shot" --window-size=1600,1000 `
  --screenshot="$PWD\docs\architecture.png" "file:///$($PWD -replace '\\','/')/docs/architecture/architecture.html"
```
