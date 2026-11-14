"""Original, programmatically drawn toolbar icons for VibeDownloader.

These are deliberately not based on IDM artwork. They provide a familiar
Windows-utility silhouette while keeping VibeDownloader's visual identity.
"""

from PIL import Image, ImageDraw


def _canvas(size):
    scale = 2
    return Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0)), scale


def toolbar_icon(name, size=32):
    image, s = _canvas(size)
    draw = ImageDraw.Draw(image)

    def box(xy, fill, outline=None, width=1, radius=0):
        xy = tuple(int(v * s) for v in xy)
        if radius:
            draw.rounded_rectangle(xy, radius=radius * s, fill=fill,
                                   outline=outline, width=width * s)
        else:
            draw.rectangle(xy, fill=fill, outline=outline, width=width * s)

    def line(xy, fill, width=1):
        draw.line(tuple(int(v * s) for v in xy), fill=fill, width=width * s,
                  joint="curve")

    def poly(points, fill, outline=None):
        pts = [(int(x * s), int(y * s)) for x, y in points]
        draw.polygon(pts, fill=fill)
        if outline:
            draw.line(pts + [pts[0]], fill=outline, width=s, joint="curve")

    blue = "#1769AA"
    blue2 = "#48A7E8"
    green = "#2E9B5F"
    red = "#D34A3F"
    amber = "#E4A11B"
    ink = "#34424F"
    pale = "#EAF3F9"

    if name == "add":
        box((5, 13, 25, 27), pale, blue, radius=2)
        line((8, 17, 22, 17), blue, 2)
        line((8, 21, 18, 21), blue2, 2)
        box((19, 3, 29, 13), green, "#247A4B", radius=5)
        line((24, 5.5, 24, 10.5), "white", 2)
        line((21.5, 8, 26.5, 8), "white", 2)
    elif name == "resume":
        box((4, 4, 28, 28), "#E9F6EE", "#A7CDB6", radius=5)
        poly([(12, 8), (24, 16), (12, 24)], green, "#237447")
    elif name == "stop":
        box((4, 4, 28, 28), "#FBEDEC", "#E5B3AF", radius=5)
        box((10, 10, 22, 22), red, "#A9342C", radius=2)
    elif name == "stop_all":
        box((3, 5, 25, 27), "#FBEDEC", "#E5B3AF", radius=5)
        box((8, 10, 17, 20), red, "#A9342C", radius=1)
        box((16, 13, 25, 23), "#EE756C", "#A9342C", radius=1)
    elif name == "delete":
        box((9, 9, 23, 27), "#EEF2F5", "#8796A4", radius=2)
        box((7, 6, 25, 10), red, "#A9342C", radius=1)
        box((12, 3, 20, 7), "#F7B0AA", "#A9342C", radius=1)
        line((13, 13, 13, 23), "#8796A4", 1)
        line((19, 13, 19, 23), "#8796A4", 1)
    elif name == "clear":
        poly([(7, 20), (21, 7), (26, 12), (13, 25)], amber, "#A56E0B")
        poly([(5, 22), (13, 20), (17, 25), (9, 28)], blue2, blue)
        line((20, 20, 23, 23, 29, 16), green, 3)
    elif name == "options":
        # A simple original cog silhouette.
        for angle_box in ((13, 2, 19, 8), (13, 24, 19, 30),
                          (2, 13, 8, 19), (24, 13, 30, 19),
                          (5, 5, 10, 10), (22, 22, 27, 27),
                          (22, 5, 27, 10), (5, 22, 10, 27)):
            box(angle_box, ink, radius=1)
        draw.ellipse((7 * s, 7 * s, 25 * s, 25 * s), fill=ink)
        draw.ellipse((12 * s, 12 * s, 20 * s, 20 * s), fill="#F3F3F3")
    elif name == "scheduler":
        box((4, 6, 27, 28), "white", "#758593", radius=3)
        box((4, 6, 27, 12), blue, blue, radius=3)
        line((10, 3, 10, 9), ink, 2)
        line((21, 3, 21, 9), ink, 2)
        draw.ellipse((14 * s, 14 * s, 27 * s, 27 * s), fill=amber,
                     outline="#A56E0B", width=s)
        line((20.5, 17, 20.5, 21.5, 24, 23), "white", 2)
    elif name in ("start_queue", "stop_queue"):
        for y, color in ((6, "#A8D8F3"), (11, "#72BCE8"), (16, blue2)):
            box((4, y, 21, y + 8), color, blue, radius=1)
        if name == "start_queue":
            poly([(18, 17), (29, 23), (18, 29)], green, "#237447")
        else:
            box((19, 19, 28, 28), red, "#A9342C", radius=1)
    elif name == "browser":
        draw.ellipse((3 * s, 3 * s, 29 * s, 29 * s), fill="#EAF3F9",
                     outline=blue, width=2 * s)
        line((4, 16, 28, 16), blue, 1)
        draw.ellipse((10 * s, 3 * s, 22 * s, 29 * s), outline=blue, width=s)
        box((19, 18, 30, 29), green, "#247A4B", radius=3)
        line((24.5, 20.5, 24.5, 26.5), "white", 2)
        line((21.5, 23.5, 27.5, 23.5), "white", 2)
    else:
        box((5, 5, 27, 27), blue, "#0E4F83", radius=5)

    return image.resize((size, size), Image.Resampling.LANCZOS)
