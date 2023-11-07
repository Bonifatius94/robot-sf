from robot_sf.nav.map_config import MapDefinitionPool

map_pool = MapDefinitionPool()
map_names = map_pool.list_map_names()


def test_is_map_avialable():
    map_name = "default_map.json" 
    specific_map = map_pool.get_map_by_name(map_name)

    assert specific_map == map_name
