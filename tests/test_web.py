def test_dashboard_page_serves_assets(client):
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    for asset in ("vendor/chart.umd.min.js", "vendor/tailwind-browser.js", "js/dashboard.js", "js/brazil-map.js"):
        assert asset in html
        assert client.get(f"/static/{asset}").status_code == 200


def test_admin_page_renders_template(client):
    r = client.get("/admin/")
    assert r.status_code == 200 and "Cadastro do dia" in r.get_data(as_text=True)


def test_no_external_cdn_dependency(client):
    html = client.get("/").get_data(as_text=True) + client.get("/admin/").get_data(as_text=True)
    assert "cdn." not in html and "fonts.googleapis" not in html
