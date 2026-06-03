/**
 * Flags hardcoded directional Tailwind utility classes in JSX className strings.
 *
 * Why: this app ships Hebrew (RTL) and English (LTR) from the same DOM tree, so
 *   we standardize on logical-property classes (ps-, pe-, ms-, me-, text-start,
 *   text-end, start-, end-, border-s-, border-e-, rounded-s-, rounded-e-) and
 *   forbid the physical variants.
 *
 * Detected (configurable via `extraPatterns`):
 *   pl-N, pr-N        → use ps-N / pe-N
 *   ml-N, mr-N        → use ms-N / me-N
 *   left-N, right-N   → use start-N / end-N (Tailwind 3.3+)
 *   text-left/right   → use text-start / text-end
 *   border-l-*, -r-*  → use border-s-* / border-e-*
 *   rounded-l-*, -r-* → use rounded-s-* / rounded-e-*
 *   float-left/right  → flag (no logical replacement; prefer flexbox)
 */
const DEFAULT_PATTERN =
  /(^|\s)(p[lr]-[\w./[\]]+|m[lr]-[\w./[\]]+|(?:-?)(?:left|right)-[\w./[\]]+|text-(?:left|right)|border-[lr](?:-[\w./[\]]+)?|rounded-[lr](?:-[\w./[\]]+)?|float-(?:left|right))(\s|$)/;

function checkLiteral(context, node, value) {
  if (typeof value !== "string") return;
  const match = value.match(DEFAULT_PATTERN);
  if (!match) return;
  const offending = match[2];
  context.report({
    node,
    messageId: "hardcodedDirectional",
    data: { className: offending },
  });
}

/** @type {import('eslint').Rule.RuleModule} */
const rule = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow hardcoded LTR-only Tailwind utility classes; use logical variants for RTL-safe layout.",
    },
    schema: [],
    messages: {
      hardcodedDirectional:
        "`{{className}}` is a physical-direction Tailwind class. Use the logical variant (ps-/pe-, ms-/me-, start-/end-, text-start/-end, border-s-/-e-, rounded-s-/-e-) so RTL renders correctly.",
    },
  },
  create(context) {
    return {
      JSXAttribute(node) {
        if (node.name.name !== "className") return;
        const v = node.value;
        if (!v) return;
        if (v.type === "Literal") {
          checkLiteral(context, v, v.value);
        } else if (v.type === "JSXExpressionContainer") {
          const expr = v.expression;
          if (expr.type === "Literal") {
            checkLiteral(context, expr, expr.value);
          } else if (expr.type === "TemplateLiteral") {
            for (const q of expr.quasis) {
              checkLiteral(context, q, q.value.cooked);
            }
          }
        }
      },
    };
  },
};

export default rule;
