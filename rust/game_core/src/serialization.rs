//! Canonical JSON and FNV-1a 64 hashing (core-api §3).
//!
//! Byte-identical with `src/core/serialization/canonical.gd` and
//! `tools/reference/hash_reference.py`:
//! - objects: keys sorted recursively (code-point order == UTF-8 byte order);
//! - no whitespace; integers without fractional part or exponent;
//! - non-ASCII is NOT escaped (equivalent of Python `ensure_ascii=False`);
//! - FNV-1a 64 over UTF-8 bytes, printed as 16 UPPERCASE hex characters.

use serde_json::Value;

/// Canonical JSON string for a parsed JSON value.
pub fn to_canonical(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => write_number(n, out),
        Value::String(s) => write_json_string(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_json_string(key, out);
                out.push(':');
                write_canonical(map.get(*key).expect("key from map"), out);
            }
            out.push('}');
        }
    }
}

fn write_number(n: &serde_json::Number, out: &mut String) {
    if let Some(v) = n.as_i64() {
        out.push_str(&v.to_string());
    } else if let Some(v) = n.as_u64() {
        out.push_str(&v.to_string());
    } else if let Some(v) = n.as_f64() {
        // Floats are forbidden in state/commands/events (core-api §0); a float
        // without a fractional part still serializes as an integer so that a
        // stray `2.0` from data parsing cannot break byte compatibility.
        if v.fract() == 0.0 && v.abs() <= 9.007_199_254_740_992e15 {
            out.push_str(&format!("{}", v as i64));
        } else {
            panic!("canonical JSON: non-integer float {} is forbidden", v);
        }
    } else {
        panic!("canonical JSON: unsupported number");
    }
}

/// JSON string escaping: quotes and backslash, control characters as short
/// escapes or \\u00XX; non-ASCII stays raw UTF-8 (Godot JSON.stringify /
/// Python ensure_ascii=False).
fn write_json_string(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// FNV-1a 64 over raw bytes: `h = 0xCBF29CE484222325`;
/// per byte `h ^= byte; h = h.wrapping_mul(1099511628211)`.
pub fn fnv1a64(bytes: &[u8]) -> u64 {
    const FNV_OFFSET: u64 = 0xCBF29CE484222325;
    const FNV_PRIME: u64 = 1099511628211;
    let mut h = FNV_OFFSET;
    for &b in bytes {
        h ^= u64::from(b);
        h = h.wrapping_mul(FNV_PRIME);
    }
    h
}

/// FNV-1a 64 over the UTF-8 bytes of `text`, as 16 UPPERCASE hex characters.
pub fn fnv1a64_hex(text: &str) -> String {
    format!("{:016X}", fnv1a64(text.as_bytes()))
}

/// `state_hash` = FNV-1a 64 of the canonical form (core-api §3).
pub fn state_hash(value: &Value) -> String {
    fnv1a64_hex(&to_canonical(value))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn fnv_matches_hash_vectors() {
        // tests/golden/hash_vectors.json (canonical strings as inputs).
        assert_eq!(fnv1a64_hex(""), "CBF29CE484222325");
        assert_eq!(fnv1a64_hex("{}"), "08F44B07B5901A25");
        assert_eq!(fnv1a64_hex("{\"a\":1}"), "9C3E82DD6FCAE8B1");
        assert_eq!(
            fnv1a64_hex("{\"ships\":[{\"hp\":4,\"id\":\"A1_tie_fighter_0\"}]}"),
            "5B9B593DDB20BE1B"
        );
        assert_eq!(fnv1a64_hex("русская строка"), "BC880D90022C7EDE");
    }

    #[test]
    fn keys_are_sorted_recursively() {
        let value = json!({"b": 1, "a": {"z": 1, "y": [2, {"k": 1, "j": 2}]}});
        assert_eq!(to_canonical(&value), r#"{"a":{"y":[2,{"j":2,"k":1}],"z":1},"b":1}"#);
    }

    #[test]
    fn unicode_is_not_escaped() {
        let value = json!("русская строка");
        assert_eq!(to_canonical(&value), "\"русская строка\"");
        // Matching Python: {"k": "ы"} -> {"k":"ы"}
        let obj = json!({"k": "ы"});
        assert_eq!(to_canonical(&obj), "{\"k\":\"ы\"}");
    }

    #[test]
    fn ints_have_no_fraction_or_exponent() {
        assert_eq!(to_canonical(&json!(0)), "0");
        assert_eq!(to_canonical(&json!(-7)), "-7");
        assert_eq!(to_canonical(&json!(4294967296i64)), "4294967296");
        assert_eq!(to_canonical(&json!([true, false, null])), "[true,false,null]");
    }

    #[test]
    fn escapes_and_control_chars() {
        let value = json!("a\"b\\c\nd\u{1}");
        assert_eq!(to_canonical(&value), "\"a\\\"b\\\\c\\nd\\u0001\"");
    }
}
