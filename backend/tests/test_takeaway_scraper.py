import xml.etree.ElementTree as ET
from scrapers import takeaway


def test_sign_produces_md5():
    sig = takeaway._sign("getrestaurants", "1000", "BE")
    assert len(sig) == 32
    assert sig == takeaway._sign("getrestaurants", "1000", "BE")


def test_parse_menu_items():
    xml = """<r>
      <mc><cs><ct>
        <nm>Pizzas</nm>
        <ps>
          <pr><nm>Margherita</nm><pc>899</pc></pr>
          <pr><nm>Quattro Formaggi</nm><pc>1150</pc></pr>
        </ps>
      </ct></cs></mc>
    </r>"""
    root = ET.fromstring(xml)
    items, fee = takeaway._parse_menu(root)
    assert len(items) == 2
    assert items[0]["title"] == "Margherita"
    assert items[0]["price"] == 8.99
    assert items[0]["catalog_name"] == "Pizzas"
    assert items[1]["price"] == 11.50
    assert fee is None


def test_parse_menu_with_delivery_fee():
    xml = """<r>
      <mc><cs><ct>
        <nm>Burgers</nm>
        <ps><pr><nm>Burger</nm><pc>1200</pc></pr></ps>
      </ct></cs></mc>
      <dd><da><co><ct>199</ct></co></da></dd>
    </r>"""
    root = ET.fromstring(xml)
    items, fee = takeaway._parse_menu(root)
    assert fee == 1.99
    assert len(items) == 1


def test_parse_menu_empty():
    root = ET.fromstring("<r></r>")
    items, fee = takeaway._parse_menu(root)
    assert items == []
    assert fee is None


def test_parse_restaurants():
    xml = """<r>
      <rt>
        <id>12345</id>
        <nm>Test Pizza</nm>
        <bn>Ixelles</bn>
        <ad><lt>50.85</lt><ln>4.35</ln></ad>
        <rv>4.5</rv>
        <est>30-45</est>
      </rt>
    </r>"""
    root = ET.fromstring(xml)
    rests = takeaway._parse_restaurants(root)
    assert len(rests) == 1
    assert rests[0]["name"] == "Test Pizza Ixelles"
    assert rests[0]["id"] == "12345"
    assert rests[0]["lat"] == 50.85
    assert rests[0]["rating"] == 4.5


def test_parse_restaurants_no_branch():
    xml = """<r><rt><id>1</id><nm>Solo</nm><rv></rv><est></est></rt></r>"""
    root = ET.fromstring(xml)
    rests = takeaway._parse_restaurants(root)
    assert rests[0]["name"] == "Solo"
