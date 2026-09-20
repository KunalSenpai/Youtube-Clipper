import unittest

from youtube_clipper.video.captions import normalize_caption_style


class CaptionStyleTests(unittest.TestCase):
    def test_style_values_are_normalized(self):
        style = normalize_caption_style({
            "font_name": "Montserrat",
            "font_size": "52",
            "text_color": "#f4d35e",
            "outline_color": "#101010",
            "outline": "4",
            "shadow": 2,
            "position": "middle",
            "margin": "120",
        })
        self.assertEqual(style["font_name"], "Montserrat")
        self.assertEqual(style["font_size"], 52)
        self.assertEqual(style["text_color"], "#F4D35E")
        self.assertEqual(style["position"], "middle")

    def test_invalid_colors_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "six-digit color"):
            normalize_caption_style({"text_color": "white"})

    def test_unsafe_font_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "font"):
            normalize_caption_style({"font_name": r"Arial{\\bad}"})


if __name__ == "__main__":
    unittest.main()
