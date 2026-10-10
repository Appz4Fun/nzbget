//! NntpConnection's protocol (NntpConnection.cpp): a request with the
//! re-login a 480 answer asks for, the AUTHINFO USER/PASS exchange, the
//! greeting on connect and changing the group, as the C++ did them. The
//! connection's I/O, its error reporting and the line buffer stay C++:
//! answers are the C++ line buffer, which the exchange cuts at its last CR
//! for error messages, as before.

use std::ffi::{c_char, CStr, CString};

/// A C++ callback failed (it threw): stop, the C++ wrapper rethrows.
#[derive(Debug, PartialEq)]
pub struct Abort;

/// The connection, as the exchange uses it.
pub trait Io {
    fn write_line(&mut self, line: &CStr) -> Result<(), Abort>;
    /// The next line in the C++ line buffer (NUL-terminated), or null.
    fn read_line(&mut self) -> Result<*mut c_char, Abort>;
    /// Connection::ReportError(prefix, arg, false, 0)
    fn report_error(&mut self, prefix: &CStr, arg: &CStr) -> Result<(), Abort>;
    fn debug(&mut self, msg: &CStr) -> Result<(), Abort>;
    /// GetStatus() == csCancelled
    fn cancelled(&mut self) -> Result<bool, Abort>;
    fn user(&self) -> &CStr;
    fn password(&self) -> &CStr;
    /// the news server's name and host, and the connection's host
    fn name(&self) -> &CStr;
    fn host(&self) -> &CStr;
    fn conn_host(&self) -> &CStr;
}

/// The login state NntpConnection keeps.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Auth {
    pub error: bool,
    pub rejected: bool,
}

/// BString<1024>: printf's output cut to 1023 bytes, as a C string.
fn bstring(parts: &[&[u8]]) -> CString {
    let mut v: Vec<u8> = parts.concat();
    v.truncate(1023);
    // the parts are C strings: no NUL inside
    CString::new(v).expect("no NUL")
}

/// A message format with "%s" fields, filled as printf would (a null
/// argument printing as "(null)", extra arguments ignored).
fn format(fmt: &[u8], args: &[Option<&[u8]>]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut args = args.iter();
    let mut i = 0;
    while i < fmt.len() {
        if fmt[i] == b'%' && fmt.get(i + 1) == Some(&b's') {
            out.extend_from_slice(args.next().copied().flatten().unwrap_or(b"(null)"));
            i += 2;
        } else {
            out.push(fmt[i]);
            i += 1;
        }
    }
    out
}

fn answer_bytes<'a>(answer: *mut c_char) -> &'a [u8] {
    // the C++ line buffer: NUL-terminated
    unsafe { CStr::from_ptr(answer) }.to_bytes()
}

/// ReportErrorAnswer
fn report_answer(io: &mut dyn Io, prefix: &[u8], answer: Option<&[u8]>) -> Result<(), Abort> {
    let text = format(prefix, &[Some(io.name().to_bytes()), Some(io.host().to_bytes()), answer]);
    let msg = bstring(&[&text]);
    io.report_error(c"%s", &msg)
}

/// Cuts the answer at its last CR (for the message), notes a 502 refusal
/// and reports it unless the connection was cancelled.
fn failed_answer(io: &mut dyn Io, auth: &mut Auth, answer: *mut c_char) -> Result<bool, Abort> {
    let bytes = answer_bytes(answer);
    if let Some(cr) = bytes.iter().rposition(|&b| b == b'\r') {
        // inside the C++ buffer, before its NUL
        unsafe { *answer.add(cr) = 0 };
    }
    let bytes = answer_bytes(answer);
    auth.rejected = bytes.starts_with(b"502");
    if !io.cancelled()? {
        report_answer(io, b"Authorization for %s (%s) failed: %s", Some(bytes))?;
    }
    Ok(false)
}

fn auth_info_pass(io: &mut dyn Io, auth: &mut Auth, mut recur: i32) -> Result<bool, Abort> {
    loop {
        if recur > 10 {
            return Ok(false);
        }
        let line = bstring(&[b"AUTHINFO PASS ", io.password().to_bytes(), b"\r\n"]);
        io.write_line(&line)?;
        let answer = io.read_line()?;
        if answer.is_null() {
            report_answer(io, b"Authorization failed for %s (%s): Connection closed by remote host", None)?;
            return Ok(false);
        }
        let bytes = answer_bytes(answer);
        if bytes.starts_with(b"2") {
            {
            let msg = bstring(&[b"Authorization for ", io.conn_host().to_bytes(), b" successful"]);
            io.debug(&msg)?;
        }
            return Ok(true);
        }
        if bytes.starts_with(b"381") {
            recur += 1;
            continue;
        }
        return failed_answer(io, auth, answer);
    }
}

fn auth_info_user(io: &mut dyn Io, auth: &mut Auth, mut recur: i32) -> Result<bool, Abort> {
    loop {
        if recur > 10 {
            return Ok(false);
        }
        let line = bstring(&[b"AUTHINFO USER ", io.user().to_bytes(), b"\r\n"]);
        io.write_line(&line)?;
        let answer = io.read_line()?;
        if answer.is_null() {
            report_answer(io, b"Authorization for %s (%s) failed: Connection closed by remote host", None)?;
            return Ok(false);
        }
        let bytes = answer_bytes(answer);
        if bytes.starts_with(b"281") {
            {
            let msg = bstring(&[b"Authorization for ", io.conn_host().to_bytes(), b" successful"]);
            io.debug(&msg)?;
        }
            return Ok(true);
        }
        if bytes.starts_with(b"381") {
            recur += 1;
            return auth_info_pass(io, auth, recur);
        }
        if bytes.starts_with(b"480") {
            recur += 1;
            continue;
        }
        return failed_answer(io, auth, answer);
    }
}

/// NntpConnection::Authenticate
pub fn authenticate(io: &mut dyn Io, auth: &mut Auth) -> Result<bool, Abort> {
    if io.user().is_empty() || io.password().is_empty() {
        let host = io.host().to_owned();
        io.report_error(
            c"Could not connect to %s: server requested authorization but username/password are not set in settings",
            &host,
        )?;
        auth.error = true;
        return Ok(false);
    }
    auth.error = !auth_info_user(io, auth, 0)?;
    Ok(!auth.error)
}

/// NntpConnection::Request: the answer (the C++ line buffer) or null.
pub fn request(io: &mut dyn Io, auth: &mut Auth, req: &CStr) -> Result<*mut c_char, Abort> {
    *auth = Auth::default();
    io.write_line(req)?;
    let answer = io.read_line()?;
    if answer.is_null() {
        return Ok(answer);
    }
    if answer_bytes(answer).starts_with(b"480") {
        {
            let msg = bstring(&[io.conn_host().to_bytes(), b" requested authorization"]);
            io.debug(&msg)?;
        }
        if !authenticate(io, auth)? {
            return Ok(std::ptr::null_mut());
        }
        // try again
        io.write_line(req)?;
        return io.read_line();
    }
    Ok(answer)
}

/// NntpConnection::Connect after the socket connected: 0 connected, 1 the
/// greeting failed (the C++ disconnects), 2 the login failed.
pub fn handshake(io: &mut dyn Io, auth: &mut Auth) -> Result<i32, Abort> {
    let answer = io.read_line()?;
    if answer.is_null() {
        report_answer(io, b"Connection to %s (%s) failed: Connection closed by remote host", None)?;
        return Ok(1);
    }
    let bytes = answer_bytes(answer);
    if !bytes.starts_with(b"2") {
        report_answer(io, b"Connection to %s (%s) failed: %s", Some(bytes))?;
        return Ok(1);
    }
    if !io.user().is_empty() && !io.password().is_empty() && !authenticate(io, auth)? {
        return Ok(2);
    }
    {
            let msg = bstring(&[b"Connection to ", io.conn_host().to_bytes(), b" established"]);
            io.debug(&msg)?;
        }
    Ok(0)
}

/// NntpConnection::JoinGroup when not in `group` yet: the answer, and
/// whether the group changed.
pub fn join_group(io: &mut dyn Io, auth: &mut Auth, group: &CStr) -> Result<(*mut c_char, bool), Abort> {
    let req = bstring(&[b"GROUP ", group.to_bytes(), b"\r\n"]);
    let answer = request(io, auth, &req)?;
    if !answer.is_null() && answer_bytes(answer).starts_with(b"2") {
        {
            let msg = bstring(&[b"Changed group to ", group.to_bytes(), b" on ", io.conn_host().to_bytes()]);
            io.debug(&msg)?;
        }
        return Ok((answer, true));
    }
    let text = if answer.is_null() { &b"(null)"[..] } else { answer_bytes(answer) };
    {
            let msg = bstring(&[b"Error changing group on ", io.conn_host().to_bytes(), b" to ", group.to_bytes(), b": ", text, b"."]);
            io.debug(&msg)?;
        }
    Ok((answer, false))
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Script {
        answers: Vec<Option<Vec<u8>>>,
        buf: Vec<u8>,
        written: Vec<Vec<u8>>,
        errors: Vec<Vec<u8>>,
    }

    impl Io for Script {
        fn write_line(&mut self, line: &CStr) -> Result<(), Abort> {
            self.written.push(line.to_bytes().to_vec());
            Ok(())
        }
        fn read_line(&mut self) -> Result<*mut c_char, Abort> {
            match self.answers.remove(0) {
                None => Ok(std::ptr::null_mut()),
                Some(a) => {
                    self.buf = a;
                    self.buf.push(0);
                    Ok(self.buf.as_mut_ptr().cast())
                }
            }
        }
        fn report_error(&mut self, prefix: &CStr, arg: &CStr) -> Result<(), Abort> {
            self.errors.push([prefix.to_bytes(), b"|", arg.to_bytes()].concat());
            Ok(())
        }
        fn debug(&mut self, _: &CStr) -> Result<(), Abort> {
            Ok(())
        }
        fn cancelled(&mut self) -> Result<bool, Abort> {
            Ok(false)
        }
        fn user(&self) -> &CStr {
            c"me"
        }
        fn password(&self) -> &CStr {
            c"pw"
        }
        fn name(&self) -> &CStr {
            c"news"
        }
        fn host(&self) -> &CStr {
            c"news.example"
        }
        fn conn_host(&self) -> &CStr {
            c"news.example"
        }
    }

    fn script(answers: &[Option<&[u8]>]) -> Script {
        Script { answers: answers.iter().map(|a| a.map(<[u8]>::to_vec)).collect(), buf: Vec::new(), written: Vec::new(), errors: Vec::new() }
    }

    #[test]
    fn relogin() {
        let mut io = script(&[Some(b"480 auth"), Some(b"381 pass"), Some(b"281 ok"), Some(b"222 body")]);
        let mut auth = Auth::default();
        let a = request(&mut io, &mut auth, c"BODY <x>\r\n").unwrap();
        assert_eq!(answer_bytes(a), b"222 body");
        assert_eq!(io.written, [b"BODY <x>\r\n".to_vec(), b"AUTHINFO USER me\r\n".to_vec(), b"AUTHINFO PASS pw\r\n".to_vec(), b"BODY <x>\r\n".to_vec()]);
    }

    #[test]
    fn rejected() {
        let mut io = script(&[Some(b"200 hi"), Some(b"502 no\r\n")]);
        let mut auth = Auth::default();
        assert_eq!(handshake(&mut io, &mut auth), Ok(2));
        assert!(auth.error && auth.rejected);
        assert_eq!(io.errors, [b"%s|Authorization for news (news.example) failed: 502 no".to_vec()]);
    }
}
