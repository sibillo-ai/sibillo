---
name: images-and-media
description: Use to resize, convert, crop or combine images, and to cut, convert, compress or inspect audio and video files.
---

# Images, audio and video

The sandbox has ImageMagick (`magick`), ffmpeg and ffprobe, and python3 has pillow. Install
nothing.

## Images with magick

```sh
magick identify photo.jpg                               # size, format and colours
magick photo.heic photo.jpg                             # convert, by the output's extension
magick photo.jpg -resize 1600x1600\> -quality 85 small.jpg   # shrink to fit, never enlarge
magick photo.jpg -crop 800x600+100+50 +repage crop.jpg  # crop width x height + left + top
magick a.png b.png +append side-by-side.png             # combine; -append stacks them
magick *.jpg album.pdf                                  # images into one PDF
```

Use `-auto-orient` on photos from phones, so that they keep the way they were taken.

## Images in Python: pillow

```python
from PIL import Image, ImageOps

image = ImageOps.exif_transpose(Image.open("photo.jpg"))
image.thumbnail((1200, 1200))
image.save("/workspace/thumb.webp", quality=80)
```

## Audio and video with ffmpeg and ffprobe

```sh
ffprobe -hide_banner in.mp4                             # streams, duration, codecs
ffmpeg -i in.mov -c:v libx264 -crf 23 -c:a aac out.mp4  # convert to a widely playable MP4
ffmpeg -ss 00:01:00 -to 00:02:30 -i in.mp4 -c copy clip.mp4   # cut, without re-encoding
ffmpeg -i in.mp4 -vn -c:a libmp3lame -q:a 2 audio.mp3   # keep only the sound
ffmpeg -i in.mp4 -vf "fps=1/10,scale=640:-2" frame-%03d.png   # one frame every 10 seconds
ffmpeg -i voice.m4a -ar 16000 -ac 1 voice.wav           # mono 16 kHz, as speech tools want
```

Long encodes can run out of the command's time: use `start_command` for them and check on
them, and prefer `-c copy` when the format allows it. There is no GPU.
