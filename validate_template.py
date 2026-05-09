import re

with open('templates/base.html', 'r') as f:
    content = f.read()

# Count block definitions
blocks = len(re.findall(r'{% block content %}', content))
print(f"✅ {{% block content %}} definitions: {blocks} (expected: 1)")

# Count if/endif
ifs = len(re.findall(r'{%\s*if\s', content))
endifs = len(re.findall(r'{%\s*endif\s*%}', content))
print(f"✅ {{% if %}} count: {ifs}, {{% endif %}} count: {endifs} (balanced: {ifs == endifs})")

# Count for/endfor
fors = len(re.findall(r'{%\s*for\s', content))
endfor_count = len(re.findall(r'{%\s*endfor\s*%}', content))
print(f"✅ {{% for %}} count: {fors}, {{% endfor %}} count: {endfor_count} (balanced: {fors == endfor_count})")

# Count with/endwith
withs = len(re.findall(r'{%\s*with\s', content))
endwiths = len(re.findall(r'{%\s*endwith\s*%}', content))
print(f"✅ {{% with %}} count: {withs}, {{% endwith %}} count: {endwiths} (balanced: {withs == endwiths})")

# Count elif
elifs = len(re.findall(r'{%\s*elif\s', content))
print(f"✅ {{% elif %}} count: {elifs}")

# Count else
elses = len(re.findall(r'{%\s*else\s*%}', content))
print(f"✅ {{% else %}} count: {elses}")

if blocks == 1 and ifs == endifs and fors == endfor_count and withs == endwiths:
    print("\n✅ All Jinja2 tags are balanced!")
    print("✅ Only ONE {% block content %} definition exists!")
else:
    print("\n❌ Tag balance issue detected!")
