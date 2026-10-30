"""Check actual schemas, serialized widget order and native subgraph boundary links."""
import json
import unittest
from test_nodes import ROOT, package


class WorkflowTests(unittest.TestCase):
    def test_example_schemas_ports_and_native_configuration_subgraphs(self):
        files = list((ROOT / 'examples').glob('*.json'))
        self.assertEqual(len(files), 7)
        for file in files:
            with self.subTest(file=file.name):
                graph = json.loads(file.read_text(encoding='utf-8'))
                subgraphs = graph['definitions']['subgraphs']
                self.assertEqual(len(subgraphs), 1)
                subgraph = subgraphs[0]
                self.assertEqual(subgraph['outputs'][0]['type'], 'SAMUEL_ENHANCER_CONFIG')
                self.assertEqual(subgraph['outputs'][0]['linkIds'], [3])
                self.assertEqual(subgraph['links'][-1]['target_id'], -20)
                for layer in (graph, subgraph):
                    nodes = {node['id']: node for node in layer['nodes']}
                    for node in nodes.values():
                        if node['type'] not in package.NODE_CLASS_MAPPINGS:
                            continue
                        schema = package.NODE_CLASS_MAPPINGS[node['type']].INPUT_TYPES()
                        controls = []
                        ports = []
                        for name, definition in {**schema['required'], **schema.get('optional', {})}.items():
                            kind = definition[0]
                            options = definition[1] if len(definition) > 1 else {}
                            if options.get('forceInput') or (not isinstance(kind, list) and kind not in ('STRING', 'INT', 'FLOAT', 'BOOLEAN')):
                                ports.append(name)
                            else:
                                controls.append(definition)
                        self.assertEqual([v['name'] for v in node['inputs']], ports)
                        self.assertEqual(len(node['widgets_values']), len(controls))
                        for definition, value in zip(controls, node['widgets_values']):
                            if isinstance(definition[0], list):
                                self.assertIn(value, definition[0])
                    for serialized in layer['links']:
                        if isinstance(serialized, list):
                            link_id, source, out_slot, target, in_slot, datatype = serialized
                        else:
                            link_id, source, out_slot, target, in_slot, datatype = [serialized[k] for k in
                                ('id', 'origin_id', 'origin_slot', 'target_id', 'target_slot', 'type')]
                        self.assertEqual(nodes[source]['outputs'][out_slot]['type'], datatype)
                        self.assertIn(link_id, nodes[source]['outputs'][out_slot]['links'])
                        if target != -20:
                            self.assertEqual(nodes[target]['inputs'][in_slot]['type'], datatype)
                            self.assertEqual(nodes[target]['inputs'][in_slot]['link'], link_id)


if __name__ == '__main__':
    unittest.main()
