# Remux

Conversor gráfico para Windows de **MP4 a MKV sin recodificar**.

Usa FFmpeg en modo `stream copy`, por lo que no cambia la calidad del video ni del audio. En la práctica, la velocidad depende principalmente del disco.

## Uso rápido

### Opción 1: Remux.exe

1. Abrí la pestaña **Actions** del repositorio.
2. Entrá en el último workflow **Build Windows EXE**.
3. Descargá el artefacto **Remux-Windows**.
4. Extraé el ZIP y ejecutá `Remux.exe`.
5. Agregá uno o varios `.mp4` y pulsá **Convertir a MKV**.

Si FFmpeg no está instalado, Remux ofrece descargarlo automáticamente para este programa en `%LOCALAPPDATA%\Remux\bin`.

### Opción 2: desde Python

En Windows, hacé doble clic en `run.bat` o ejecutá:

```powershell
python remux_gui.py
```

No requiere paquetes de Python externos: la interfaz usa Tkinter de la instalación estándar de Python.

## Funciones

- selección múltiple de MP4;
- remux MP4 → MKV sin pérdida (`-c copy`);
- conserva las pistas y metadata que FFmpeg puede copiar al contenedor MKV;
- salida junto al archivo original o en una carpeta elegida;
- evita sobrescribir archivos existentes (`video_1.mkv`, `video_2.mkv`, etc.);
- barra de progreso;
- cancelación;
- detección automática de FFmpeg/ffprobe;
- instalación automática de FFmpeg si falta;
- build portable `.exe` mediante PyInstaller y GitHub Actions.

## Qué hace internamente

El comando principal es equivalente a:

```powershell
ffmpeg -i video.mp4 -map 0 -map_metadata 0 -map_chapters 0 -c copy video.mkv
```

No se decodifica ni vuelve a codificar el contenido audiovisual.

## FFmpeg

Remux no redistribuye FFmpeg dentro del repositorio. La instalación automática descarga el build Essentials para Windows desde `gyan.dev` y lo guarda únicamente en el perfil local del usuario.
