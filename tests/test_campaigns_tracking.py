from src.campaigns import tracking


def test_pixel_gif_is_a_valid_minimal_gif():
    assert tracking.PIXEL_GIF[:6] in (b"GIF89a", b"GIF87a")


def test_pixel_url_builds_expected_path():
    url = tracking.pixel_url("https://exemplo.com/", "tok123")
    assert url == "https://exemplo.com/track/open/tok123.gif"


def test_click_url_encodes_destination():
    url = tracking.click_url("https://exemplo.com", "tok123", "https://leactis.com.br/pagina?a=1")
    assert url.startswith("https://exemplo.com/track/click/tok123?url=")
    assert "leactis.com.br" in url


def test_pixel_img_tag_includes_open_tracking_url():
    tag = tracking.pixel_img_tag("https://exemplo.com", "tok123")
    assert "<img" in tag
    assert "track/open/tok123.gif" in tag
