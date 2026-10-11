//! boost::json::parse with the default parse_options (Json::Deserialize in
//! daemon/util/Json.cpp): strict RFC 8259 (no comments, trailing commas,
//! NaN/Infinity or invalid UTF-8/UTF-16), at most 32 nested containers, a
//! duplicate key replacing the earlier value in its place, and numbers as
//! Boost's imprecise parser gives them - int64, then uint64, else a double
//! from the leading digits it keeps (which depend on whether the number is
//! followed by at least 33 bytes of input, Boost's fast path) and its table
//! of powers of ten.

use std::collections::HashMap;
use std::sync::OnceLock;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Bool(bool),
    Int(i64),
    Uint(u64),
    Double(f64),
    String(Vec<u8>),
    Array(Vec<Value>),
    Object(Vec<(Vec<u8>, Value)>),
}

impl Value {
    pub fn is_number(&self) -> bool {
        matches!(self, Value::Int(_) | Value::Uint(_) | Value::Double(_))
    }

    /// value::to_number<double>.
    pub fn to_f64(&self) -> Option<f64> {
        match *self {
            Value::Int(i) => Some(i as f64),
            Value::Uint(u) => Some(u as f64),
            Value::Double(d) => Some(d),
            _ => None,
        }
    }

    /// object::if_contains: the value of a key (keys are unique).
    pub fn get(&self, key: &[u8]) -> Option<&Value> {
        match self {
            Value::Object(members) => members.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }
}

const MAX_DEPTH: usize = 32;

/// Boost's handler limits depend on its build configuration and address model.
/// The C++ caller supplies string::max_size(), array::max_size(), object::max_size().
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Limits {
    pub string: usize,
    pub array: usize,
    pub object: usize,
}

#[cfg(test)]
pub const TEST_LIMITS: Limits = Limits { string: 0x7ffffffe, array: 0x7ffffffe, object: 0x7ffffffe };

/// The value, or None for any parse error.
pub fn parse(s: &[u8], limits: Limits) -> Option<Value> {
    let mut p = Parser { s, i: 0, depth: 0, limits };
    p.ws();
    let v = p.value()?;
    p.ws();
    (p.i == s.len()).then_some(v)
}

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
    depth: usize,
    limits: Limits,
}

impl Parser<'_> {
    fn peek(&self) -> Option<u8> {
        self.s.get(self.i).copied()
    }

    fn ws(&mut self) {
        while matches!(self.peek(), Some(b' ' | b'\t' | b'\n' | b'\r')) {
            self.i += 1;
        }
    }

    fn eat(&mut self, b: u8) -> Option<()> {
        (self.peek()? == b).then(|| self.i += 1)
    }

    fn value(&mut self) -> Option<Value> {
        match self.peek()? {
            b'{' => self.object(),
            b'[' => self.array(),
            b'"' => self.string().map(Value::String),
            b't' => self.literal(b"true", Value::Bool(true)),
            b'f' => self.literal(b"false", Value::Bool(false)),
            b'n' => self.literal(b"null", Value::Null),
            b'-' | b'0'..=b'9' => {
                let (v, end) = number(self.s, self.i)?;
                self.i = end;
                Some(v)
            }
            _ => None,
        }
    }

    fn literal(&mut self, word: &[u8], v: Value) -> Option<Value> {
        self.s[self.i..].starts_with(word).then(|| {
            self.i += word.len();
            v
        })
    }

    fn enter(&mut self) -> Option<()> {
        self.depth += 1;
        (self.depth <= MAX_DEPTH).then_some(())
    }

    fn array(&mut self) -> Option<Value> {
        self.enter()?;
        self.i += 1;
        let mut items = Vec::new();
        self.ws();
        if self.eat(b']').is_none() {
            loop {
                if items.len() == self.limits.array { return None; }
                items.push(self.value()?);
                self.ws();
                match self.peek()? {
                    b',' => {
                        self.i += 1;
                        self.ws();
                    }
                    b']' => {
                        self.i += 1;
                        break;
                    }
                    _ => return None,
                }
            }
        }
        self.depth -= 1;
        Some(Value::Array(items))
    }

    fn object(&mut self) -> Option<Value> {
        self.enter()?;
        self.i += 1;
        let mut members: Vec<(Vec<u8>, Value)> = Vec::new();
        let mut index: HashMap<Vec<u8>, usize> = HashMap::new();
        // Boost counts input members, including duplicate keys.
        let mut count = 0;
        self.ws();
        if self.eat(b'}').is_none() {
            loop {
                if self.peek()? != b'"' {
                    return None;
                }
                if count == self.limits.object { return None; }
                count += 1;
                let key = self.string()?;
                self.ws();
                self.eat(b':')?;
                self.ws();
                let v = self.value()?;
                match index.get(&key) {
                    Some(&at) => members[at].1 = v,
                    None => {
                        index.insert(key.clone(), members.len());
                        members.push((key, v));
                    }
                }
                self.ws();
                match self.peek()? {
                    b',' => {
                        self.i += 1;
                        self.ws();
                    }
                    b'}' => {
                        self.i += 1;
                        break;
                    }
                    _ => return None,
                }
            }
        }
        self.depth -= 1;
        Some(Value::Object(members))
    }

    fn hex4(&mut self) -> Option<u32> {
        let digits = self.s.get(self.i..self.i + 4)?;
        let mut v = 0;
        for &d in digits {
            v = v * 16 + (d as char).to_digit(16)?;
        }
        self.i += 4;
        Some(v)
    }

    fn string(&mut self) -> Option<Vec<u8>> {
        self.i += 1;
        let mut out = Vec::new();
        loop {
            let start = self.i;
            while let Some(b) = self.peek() {
                if b == b'"' || b == b'\\' || b < 0x20 {
                    break;
                }
                self.i += 1;
            }
            let run = &self.s[start..self.i];
            if run.len() > self.limits.string - out.len() { return None; }
            std::str::from_utf8(run).ok()?;
            out.extend_from_slice(run);
            match self.peek()? {
                b'"' => {
                    self.i += 1;
                    return Some(out);
                }
                b'\\' => {
                    self.i += 1;
                    let e = self.peek()?;
                    self.i += 1;
                    let ch = match e {
                        b'"' => '"',
                        b'\\' => '\\',
                        b'/' => '/',
                        b'b' => '\u{8}',
                        b'f' => '\u{c}',
                        b'n' => '\n',
                        b'r' => '\r',
                        b't' => '\t',
                        b'u' => {
                            let hi = self.hex4()?;
                            let cp = match hi {
                                0xD800..=0xDBFF => {
                                    self.eat(b'\\')?;
                                    self.eat(b'u')?;
                                    let lo = self.hex4()?;
                                    if !(0xDC00..=0xDFFF).contains(&lo) {
                                        return None;
                                    }
                                    0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)
                                }
                                0xDC00..=0xDFFF => return None,
                                _ => hi,
                            };
                            char::from_u32(cp)?
                        }
                        _ => return None,
                    };
                    let mut buf = [0; 4];
                    let encoded = ch.encode_utf8(&mut buf).as_bytes();
                    if encoded.len() > self.limits.string - out.len() { return None; }
                    out.extend_from_slice(encoded);
                }
                _ => return None,
            }
        }
    }
}

/// detail::pow10: the double literals 1e-308..1e308.
fn pow10(exp: i32) -> f64 {
    static TABLE: OnceLock<Vec<f64>> = OnceLock::new();
    if exp > 308 {
        return f64::INFINITY;
    }
    if exp < -308 {
        return 0.0;
    }
    let table = TABLE.get_or_init(|| (-308..=308).map(|k| format!("1e{k}").parse().unwrap()).collect());
    table[(exp + 308) as usize]
}

/// detail::dec_to_float.
fn dec_to_float(m: u64, mut e: i32, neg: bool) -> f64 {
    let mut x = m as f64;
    if neg {
        x = -x;
    }
    if e < -305 {
        x *= 1e-305;
        e += 305;
    }
    if (-22..0).contains(&e) {
        return x / pow10(-e);
    }
    x * pow10(e)
}

fn digit(c: Option<u8>) -> Option<u64> {
    c.filter(u8::is_ascii_digit).map(|c| (c - b'0') as u64)
}

/// basic_parser::parse_number with number_precision::imprecise on a complete
/// input: the value and the index after it.
fn number(s: &[u8], start: usize) -> Option<(Value, usize)> {
    #[derive(Clone, Copy)]
    enum St { Num2, Num3, Num5, Num6, Num7, Num8, Exp1, Int, Dub }
    let neg = s[start] == b'-';
    let zero_first = s[start] == b'0';
    let nonzero_first = !neg && !zero_first;
    let mut i = start + neg as usize;
    let mut mant: u64 = 0;
    let mut bias: i32 = 0;
    let mut exp: i32 = 0;
    let mut frac = false;
    let at = |i: usize| s.get(i).copied();

    let mut st;
    if s.len() - i >= 16 + 1 + 16 {
        // the fast path
        let count = |i: usize| s[i..i + 16].iter().take_while(|c| c.is_ascii_digit()).count();
        let n1;
        if nonzero_first || (neg && s[i] != b'0') {
            n1 = count(i);
            if !nonzero_first && n1 == 0 {
                return None;
            }
            for &c in &s[i..i + n1] {
                mant = 10 * mant + (c - b'0') as u64;
            }
            i += n1;
        } else {
            n1 = 0;
            i += 1;
        }
        if n1 == 16 {
            st = St::Num2;
        } else if s[i] != b'.' {
            if s[i] | 32 == b'e' {
                i += 1;
                st = St::Exp1;
            } else {
                let v = if neg { (!mant).wrapping_add(1) } else { mant };
                return Some((Value::Int(v as i64), i));
            }
        } else {
            i += 1;
            let n2 = count(i);
            if n2 == 0 {
                return None;
            }
            if n1 + n2 >= 19 {
                st = St::Num7;
            } else {
                for &c in &s[i..i + n2] {
                    mant = 10 * mant + (c - b'0') as u64;
                }
                bias -= n2 as i32;
                i += n2;
                st = if s[i] | 32 == b'e' {
                    i += 1;
                    St::Exp1
                } else if s[i].is_ascii_digit() {
                    St::Num8
                } else {
                    St::Dub
                };
            }
        }
    } else {
        // do_num1
        match at(i) {
            Some(b'0') => {
                i += 1;
                st = St::Num6;
            }
            Some(c @ b'1'..=b'9') => {
                i += 1;
                mant = (c - b'0') as u64;
                st = St::Num2;
            }
            _ => return None,
        }
    }

    loop {
        st = match st {
            St::Num2 => {
                let (limit, last) = if neg { (922337203685477580, b'8') } else { (1844674407370955161, b'5') };
                loop {
                    match at(i) {
                        None => break St::Int,
                        Some(c) if c.is_ascii_digit() => {
                            i += 1;
                            if mant > limit || (mant == limit && c > last) {
                                bias += 1;
                                break St::Num3;
                            }
                            mant = 10 * mant + (c - b'0') as u64;
                        }
                        Some(_) => break St::Num6,
                    }
                }
            }
            St::Num3 => loop {
                match at(i) {
                    None => break St::Dub,
                    Some(c) if c.is_ascii_digit() => {
                        if bias + 1 == i32::MAX {
                            return None;
                        }
                        i += 1;
                        bias += 1;
                    }
                    Some(b'.') => {
                        i += 1;
                        // do_num4: a digit required
                        digit(at(i))?;
                        i += 1;
                        break St::Num5;
                    }
                    Some(c) if c | 32 == b'e' => {
                        i += 1;
                        break St::Exp1;
                    }
                    Some(_) => break St::Dub,
                }
            },
            St::Num5 => loop {
                match at(i) {
                    Some(c) if c.is_ascii_digit() => i += 1,
                    Some(c) if c | 32 == b'e' => {
                        i += 1;
                        break St::Exp1;
                    }
                    _ => break St::Dub,
                }
            },
            St::Num6 => match at(i) {
                Some(b'.') => {
                    i += 1;
                    St::Num7
                }
                Some(c) if c | 32 == b'e' => {
                    i += 1;
                    St::Exp1
                }
                _ => St::Int,
            },
            St::Num7 => {
                digit(at(i))?;
                St::Num8
            }
            St::Num8 => loop {
                match at(i) {
                    Some(c) if c.is_ascii_digit() => {
                        i += 1;
                        if mant <= 9007199254740991 {
                            if bias - 1 == i32::MIN {
                                return None;
                            }
                            bias -= 1;
                            mant = 10 * mant + (c - b'0') as u64;
                        } else {
                            break St::Num5;
                        }
                    }
                    Some(c) if c | 32 == b'e' => {
                        i += 1;
                        break St::Exp1;
                    }
                    _ => break St::Dub,
                }
            },
            St::Exp1 => {
                match at(i) {
                    Some(b'+') => i += 1,
                    Some(b'-') => {
                        i += 1;
                        frac = true;
                    }
                    _ => {}
                }
                exp = digit(at(i))? as i32;
                i += 1;
                while let Some(d) = digit(at(i)) {
                    exp = if exp > 214748364 || (exp == 214748364 && d > 7) { i32::MAX } else { 10 * exp + d as i32 };
                    i += 1;
                }
                if frac {
                    if bias < i32::MIN + exp {
                        if exp == i32::MAX && bias < 0 && exp + bias < 308 && mant != 0 {
                            return None;
                        }
                        bias = 0;
                        exp = i32::MAX;
                    }
                } else if bias > i32::MAX - exp {
                    if exp == i32::MAX && bias > 0 && exp - bias < 308 && mant != 0 {
                        return None;
                    }
                    bias = 0;
                    exp = i32::MAX;
                }
                St::Dub
            }
            St::Int => {
                let v = if neg {
                    Value::Int((!mant).wrapping_add(1) as i64)
                } else if mant <= i64::MAX as u64 {
                    Value::Int(mant as i64)
                } else {
                    Value::Uint(mant)
                };
                return Some((v, i));
            }
            St::Dub => {
                let e = if frac { bias - exp } else { bias + exp };
                return Some((Value::Double(dec_to_float(mant, e, neg)), i));
            }
        };
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(s: &[u8]) -> Option<Value> { super::parse(s, TEST_LIMITS) }

    #[test]
    fn handler_limits() {
        let limited = |s: &[u8]| super::parse(s, Limits { string: 4, array: 2, object: 2 });
        for s in [b"[0,0]".as_slice(), br#"{"a":0,"a":1}"#, br#""abcd""#, br#""\ud83d\ude00""#] {
            assert!(limited(s).is_some());
        }
        for s in [b"[0,0,0]".as_slice(), br#"{"a":0,"a":1,"a":2}"#, br#""abcde""#,
            br#""a\ud83d\ude00""#, br#""\ud83d\ude00a""#, br#"{"abcde":0}"#] {
            assert!(limited(s).is_none());
        }
    }

    #[test]
    fn grammar() {
        for ok in [&b"{}"[..], b" \t\r\n[1, 2]", b"\"\\ud83d\\ude00\"", b"\"\x7f\"", b"-0", b"[1E5]", b"true", b"null"] {
            assert!(parse(ok).is_some(), "{:?}", String::from_utf8_lossy(ok));
        }
        for bad in [&b""[..], b" ", b"\x0c{}", b"[1,]", b"{\"a\":1/*c*/}", b"\"\\ud800\"", b"\"\\udc00\"", b"\"\xff\"",
                    b"\"\xc0\x80\"", b"\"\xed\xa0\x80\"", b"\"\xf4\x90\x80\x80\"", b"\xef\xbb\xbf{}", b"{} x", b"01", b"1.",
                    b"[1e]", b"[.5]", b"[+1]", b"[NaN]", b"[-]", b"[-01]", b"tru", b"nullx", b"\"\t\"", b"\"\\a\"",
                    b"\"\\u12\"", b"\"\\ud800\\u0041\"", b"{1:2}", b"{\"a\" 1}"] {
            assert!(parse(bad).is_none(), "{:?}", String::from_utf8_lossy(bad));
        }
        let deep = |d: usize| [vec![b'['; d], b"1".to_vec(), vec![b']'; d]].concat();
        assert!(parse(&deep(32)).is_some());
        assert!(parse(&deep(33)).is_none());
        assert_eq!(parse(b"{\"a\":1,\"b\":3,\"a\":2}"),
            Some(Value::Object(vec![(b"a".to_vec(), Value::Int(2)), (b"b".to_vec(), Value::Int(3))])));
        assert_eq!(parse(b"\"a\\u0000b\""), Some(Value::String(b"a\0b".to_vec())));
    }

    #[test]
    fn numbers() {
        let n = |s: &str| parse(s.as_bytes()).unwrap();
        assert_eq!(n("-0"), Value::Int(0));
        assert_eq!(n("18446744073709551615"), Value::Uint(u64::MAX));
        assert_eq!(n("9223372036854775807"), Value::Int(i64::MAX));
        assert_eq!(n("-9223372036854775808"), Value::Int(i64::MIN));
        assert_eq!(n("18446744073709551616"), Value::Double(1.8446744073709552e19));
        assert_eq!(n("1e400"), Value::Double(f64::INFINITY));
        assert_eq!(n("0.1e1"), Value::Double(1.0));
        // Boost's imprecise result, one ulp off the correctly rounded value
        assert_eq!(n("2.2250738585072011e-308"), Value::Double(2.2250738585072014e-308));
        assert_eq!(n("1e99999999999"), Value::Double(f64::INFINITY));
        assert_eq!(n("1e-99999999999"), Value::Double(0.0));
    }
}
