# `derived_ids` — provenance of the `otel_genai` rendering

Traceable to `fixtures/captured/genai_tool_call.jsonl` (**L3**, the
`execute_tool` span), by way of `single_tool_call/otel_genai.notes.md`: this
rendering is that one's span, three times, with the tool names, values and
timestamps swapped for this scenario's and `gen_ai.tool.call.id` /
`gen_ai.tool.type` dropped so no span pairs or reports an unmapped attribute.
Every key present is a key L3 carries.

## The one departure, and why it is stated rather than trimmed

**`span_id` is deleted from every record, and no observed OTel exporter omits
it.** That deletion *is* the scenario: `SPEC.md` §3.6 rule 2 exists for a
dialect that carries no span id, the library has no such adapter yet, and a
rule with no fixture is a rule nobody checks. Deleting the field is the only
way the two dialects this corpus has can put a record down the derived-id
path, and it changes nothing else about the record — every remaining key, and
every value, is L3's.

So this rendering is honest about what it is: observed output with one field
removed, not an invented dialect. Read it as "what these adapters do when the
id is missing", never as "this is what an exporter emits". When an adapter for
a dialect that genuinely carries no span id lands, it renders this scenario
from its own observed output and this note goes away.

## Why nothing but `name` is declared

`gen_ai.tool.call.arguments` and `.result` agree with `input.value` and
`output.value` in both `value` and `mime`, which is `single_tool_call`'s
finding from the 2.6 matched pair, unchanged by removing an id.
