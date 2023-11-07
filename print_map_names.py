
from robot_sf.nav.map_config import MapDefinitionPool
map_pool = MapDefinitionPool()
map_names = map_pool.list_map_names()

print(map_names)

map_name = "default_map.json" 
specific_map = map_pool.get_map_by_name(map_name)

if specific_map:
    # You have successfully loaded the map with the given name
    # specific_map is now a MapDefinition object representing the desired map
    print("Map found.") 
    # print the name of the map that was found
    print("Map " + specific_map.name + " found.")
else:
    print("Map not found.")

map_pool.get_map_by_name("test")

for name in map_names:
    print(name)