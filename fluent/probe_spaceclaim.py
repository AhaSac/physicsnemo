# Python Script, API Version = V242
# Executed by SpaceClaim, not by CPython.
import os
import json
import traceback

OUTPUT = os.environ['PUMP_PROBE_OUTPUT']
try:
    DocumentOpen.Execute(os.environ['PUMP_INPUT'])
    root = GetRootPart()
    bodies = list(root.GetAllBodies())
    data = {'bodies': [], 'groups': []}
    for body in bodies:
        entry = {'name': body.Name, 'faces': len(list(body.Faces)),
                 'shape_type': str(body.Shape.GetType())}
        data['bodies'].append(entry)
    for group in root.Groups:
        data['groups'].append({'name': group.Name,
                               'members': [str(x.GetType()) for x in group.Members]})
    with open(OUTPUT, 'w') as stream:
        json.dump(data, stream, indent=2)
except:
    with open(OUTPUT, 'w') as stream:
        json.dump({'error': traceback.format_exc()}, stream, indent=2)
    raise
