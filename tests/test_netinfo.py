# tests/test_netinfo.py
import pytest

from src import netinfo


@pytest.mark.parametrize("text", ["192.168.1.20", "10.0.0.5", "172.16.0.1", "172.31.255.254"])
def test_private_ipv4_addresses_are_lan_addresses(text):
    assert netinfo.is_lan_address(text)


@pytest.mark.parametrize("text", [
    "0.0.0.0", "127.0.0.1", "127.0.1.1", "169.254.1.1", "100.64.0.1", "8.8.8.8",
    "172.32.0.1", "172.15.255.255", "192.167.255.255", "192.169.0.1",
    # von `ipaddress.is_private` mitgezählt, aber kein RFC-1918-LAN: Testnetze, das
    # Benchmark-Netz (VPN-Tunnel mit Fake-IP wie Clash/Surge belegen 198.18.0.0/15),
    # „dieses Netz" und die IETF-Protokollzuweisung.
    "0.1.2.3", "192.0.2.1", "198.18.0.1", "198.19.255.254", "198.51.100.7", "203.0.113.5",
    "192.0.0.8", "192.0.0.170",
    "224.0.0.1", "255.255.255.255", "192.168.1.256", "192.168.001.001",
    "192.168.1", "192.168.1.20 ", " 192.168.1.20", "192.168.1.20:17654", "::1",
    "fe80::1", "fd00::1", "", "localhost", "１９２.１６８.１.２０", "192.168.1.20\n",
    None, 5, 192168120, b"192.168.1.20", ["192.168.1.20"],
])
def test_everything_else_is_not_a_lan_address(text):
    assert not netinfo.is_lan_address(text)


def test_route_address_uses_a_udp_socket_without_sending(monkeypatch):
    events = []

    class FakeSocket:
        def __init__(self, family, kind):
            events.append(("socket", family, kind))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def connect(self, address):
            events.append(("connect", address))

        def getsockname(self):
            return ("192.168.1.20", 54321)

        def sendto(self, *args):                  # darf nie gerufen werden
            events.append(("send",))

        send = sendall = sendto

    monkeypatch.setattr(netinfo.socket, "socket", FakeSocket)

    assert netinfo.route_address(("192.0.2.1", 9)) == "192.168.1.20"
    assert events[0][2] == netinfo.socket.SOCK_DGRAM
    assert ("connect", ("192.0.2.1", 9)) in events and ("send",) not in events


def test_route_address_is_none_without_a_route(monkeypatch):
    class Broken:
        def __init__(self, *args):
            raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(netinfo.socket, "socket", Broken)
    assert netinfo.route_address() is None


def test_interface_addresses_come_from_the_host_name(monkeypatch):
    monkeypatch.setattr(netinfo.socket, "gethostname", lambda: "rechner")
    monkeypatch.setattr(netinfo.socket, "getaddrinfo", lambda host, port, **kw: [
        (2, 1, 6, "", ("192.168.1.20", 0)), (2, 1, 6, "", ("10.0.0.5", 0))])

    assert netinfo.interface_addresses() == ["192.168.1.20", "10.0.0.5"]


def test_interface_addresses_survive_a_failing_lookup(monkeypatch):
    def boom(*args, **kwargs):
        raise netinfo.socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(netinfo.socket, "getaddrinfo", boom)
    assert netinfo.interface_addresses() == []


def test_candidates_put_the_route_address_first_and_drop_duplicates_and_non_lan():
    result = netinfo.lan_candidates(
        route=lambda: "192.168.1.20",
        interfaces=lambda: ["127.0.1.1", "10.0.0.5", "192.168.1.20", "169.254.3.4", "8.8.8.8"])

    assert result == ["192.168.1.20", "10.0.0.5"]


def test_candidates_without_a_route_use_the_interfaces():
    assert netinfo.lan_candidates(route=lambda: None,
                                  interfaces=lambda: ["10.0.0.5"]) == ["10.0.0.5"]


def test_candidates_are_empty_when_nothing_is_a_lan_address():
    assert netinfo.lan_candidates(route=lambda: "127.0.0.1", interfaces=lambda: []) == []


def test_the_real_candidates_are_all_lan_addresses():
    # Läuft auf jedem Rechner, auch ohne Netz (dann leer).
    assert all(netinfo.is_lan_address(a) for a in netinfo.lan_candidates())


@pytest.mark.parametrize("configured,candidates,expected", [
    ("", ["192.168.1.20", "10.0.0.5"], "192.168.1.20"),          # leer = Vorschlag
    ("", [], None),
    ("10.0.0.5", ["192.168.1.20", "10.0.0.5"], "10.0.0.5"),        # gewählte Adresse gibt es noch
    ("10.0.0.9", ["192.168.1.20", "10.0.0.5"], None),            # verschwunden: nie still ersetzt
    ("garbage", ["192.168.1.20"], None),
])
def test_pick_address(configured, candidates, expected):
    assert netinfo.pick_address(configured, candidates) == expected


def test_a_vpn_tunnel_address_is_never_suggested_as_the_default():
    assert netinfo.lan_candidates(route=lambda: "198.18.0.1",
                                  interfaces=lambda: ["192.168.1.20"]) == ["192.168.1.20"]
