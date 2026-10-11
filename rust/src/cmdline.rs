//! CommandLineParser (CommandLineParser.cpp): the command line as the C++
//! read it - getopt_long (or getopt) over the same argv array, which it
//! permutes, with the switches that read their own extra arguments by moving
//! optind - then the file argument (InitFileArg, ParseFileIdList,
//! ParseFileNameList). The parser's fields stay C++, set through a sink.

use std::ffi::{c_char, c_int, CStr};

extern "C" {
    static mut optind: c_int;
    static mut optarg: *mut c_char;
    fn getopt(argc: c_int, argv: *const *mut c_char, optstring: *const c_char) -> c_int;
    fn atoi(s: *const c_char) -> c_int;
    fn strcasecmp(a: *const c_char, b: *const c_char) -> c_int;
    fn strncasecmp(a: *const c_char, b: *const c_char, n: usize) -> c_int;
    fn getcwd(buf: *mut c_char, size: usize) -> *mut c_char;
}

const SHORT_OPTIONS: &CStr = c"c:hno:psvAB:DCE:G:K:LPR:STUQOVW:";

/// A C++ callback threw: stop (the C++ rethrows).
#[derive(Debug, PartialEq)]
pub struct Abort;

/// Integer fields (`Sink::set_int`).
pub mod field {
    pub const NO_CONFIG: i32 = 0;
    pub const PRINT_USAGE: i32 = 1;
    pub const PRINT_VERSION: i32 = 2;
    pub const PRINT_OPTIONS: i32 = 3;
    pub const SERVER_MODE: i32 = 4;
    pub const DAEMON_MODE: i32 = 5;
    pub const REMOTE_CLIENT_MODE: i32 = 6;
    /// CommandLineParser::EClientOperation's numbering
    pub const CLIENT_OPERATION: i32 = 7;
    pub const ADD_TOP: i32 = 8;
    pub const ADD_PAUSED: i32 = 9;
    pub const ADD_PRIORITY: i32 = 10;
    pub const ADD_DUPE_SCORE: i32 = 11;
    /// 0 score, 1 all, 2 force
    pub const ADD_DUPE_MODE: i32 = 12;
    /// EMatchMode: 1 id, 2 name, 3 regex
    pub const MATCH_MODE: i32 = 13;
    pub const TEST_BACKTRACE: i32 = 15;
    pub const WEB_GET: i32 = 16;
    pub const SIG_VERIFY: i32 = 17;
    pub const LOG_LINES: i32 = 18;
    /// an EditAction (C++ maps it to DownloadQueue's)
    pub const EDIT_ACTION: i32 = 19;
    pub const EDIT_OFFSET: i32 = 20;
    /// 0 info, 1 warning, 2 error, 3 detail, 4 debug
    pub const WRITE_LOG_KIND: i32 = 21;
    pub const PAUSE_DOWNLOAD: i32 = 22;
    /// getopt reported an unknown switch (m_errors, nothing printed here)
    pub const ERRORS: i32 = 23;
    // string fields (`Sink::set_str`, `Sink::steal`)
    pub const CONFIG_FILENAME: i32 = 30;
    pub const WEB_GET_FILENAME: i32 = 31;
    pub const PUB_KEY_FILENAME: i32 = 32;
    pub const SIG_FILENAME: i32 = 33;
    /// SetAddCategory
    pub const ADD_CATEGORY: i32 = 34;
    pub const LAST_ARG: i32 = 35;
    pub const ARG_FILENAME: i32 = 36;
    pub const ADD_NZB_FILENAME: i32 = 37;
    pub const ADD_DUPE_KEY: i32 = 38;
    pub const EDIT_QUEUE_TEXT: i32 = 39;
    /// The host evaluates the original (int)(atof(value) * 1024) conversion.
    pub const SET_RATE_ARG: i32 = 40;
}

/// The edit actions, in the order the C++ table maps them.
pub mod edit {
    pub const POST_DELETE: i32 = 0;
    pub const HISTORY_DELETE: i32 = 1;
    pub const HISTORY_RETURN: i32 = 2;
    pub const HISTORY_PROCESS: i32 = 3;
    pub const HISTORY_REDOWNLOAD: i32 = 4;
    pub const HISTORY_RETRY_FAILED: i32 = 5;
    pub const HISTORY_SET_PARAMETER: i32 = 6;
    pub const HISTORY_MARK_BAD: i32 = 7;
    pub const HISTORY_MARK_GOOD: i32 = 8;
    pub const HISTORY_MARK_SUCCESS: i32 = 9;
    pub const GROUP_MOVE_TOP: i32 = 10;
    pub const FILE_MOVE_TOP: i32 = 11;
    pub const GROUP_MOVE_BOTTOM: i32 = 12;
    pub const FILE_MOVE_BOTTOM: i32 = 13;
    pub const GROUP_PAUSE: i32 = 14;
    pub const FILE_PAUSE: i32 = 15;
    pub const GROUP_PAUSE_ALL_PARS: i32 = 16;
    pub const FILE_PAUSE_ALL_PARS: i32 = 17;
    pub const GROUP_PAUSE_EXTRA_PARS: i32 = 18;
    pub const FILE_PAUSE_EXTRA_PARS: i32 = 19;
    pub const GROUP_RESUME: i32 = 20;
    pub const FILE_RESUME: i32 = 21;
    pub const GROUP_DELETE: i32 = 22;
    pub const FILE_DELETE: i32 = 23;
    pub const GROUP_PARK_DELETE: i32 = 24;
    pub const GROUP_SORT_FILES: i32 = 25;
    pub const GROUP_APPLY_CATEGORY: i32 = 26;
    pub const GROUP_SET_CATEGORY: i32 = 27;
    pub const GROUP_SET_NAME: i32 = 28;
    pub const GROUP_MERGE: i32 = 29;
    pub const FILE_SPLIT: i32 = 30;
    pub const GROUP_SET_PARAMETER: i32 = 31;
    pub const GROUP_SET_PRIORITY: i32 = 32;
    pub const GROUP_MOVE_OFFSET: i32 = 33;
    pub const FILE_MOVE_OFFSET: i32 = 34;
}

/// EClientOperation
mod op {
    pub const NONE: i32 = 0;
    pub const DOWNLOAD: i32 = 1;
    pub const LIST_FILES: i32 = 2;
    pub const LIST_GROUPS: i32 = 3;
    pub const LIST_STATUS: i32 = 4;
    pub const SET_RATE: i32 = 5;
    pub const DUMP_DEBUG: i32 = 6;
    pub const EDIT_QUEUE: i32 = 7;
    pub const LOG: i32 = 8;
    pub const SHUTDOWN: i32 = 9;
    pub const RELOAD: i32 = 10;
    pub const VERSION: i32 = 11;
    pub const POST_QUEUE: i32 = 12;
    pub const WRITE_LOG: i32 = 13;
    pub const SCAN_SYNC: i32 = 14;
    pub const SCAN_ASYNC: i32 = 15;
    pub const DOWNLOAD_PAUSE: i32 = 16;
    pub const DOWNLOAD_UNPAUSE: i32 = 17;
    pub const POST_PAUSE: i32 = 18;
    pub const POST_UNPAUSE: i32 = 19;
    pub const SCAN_PAUSE: i32 = 20;
    pub const SCAN_UNPAUSE: i32 = 21;
    pub const HISTORY: i32 = 22;
    pub const HISTORY_ALL: i32 = 23;
}

/// Where the parser's results go (the C++ CommandLineParser).
pub trait Sink {
    /// Use the host C++ option table and its HAVE_GETOPT_LONG selection.
    /// Like libc getopt, this callback must not throw.
    ///
    /// # Safety
    /// The arguments and exclusive access to getopt globals must be valid
    /// for the platform libc call.
    unsafe fn getopt_long(&mut self, argc: c_int, argv: *mut *mut c_char) -> c_int;
    fn set_int(&mut self, field: i32, value: i32) -> Result<(), Abort>;
    /// Consume borrowed `value`, copying it if stored (null: a null CString).
    fn set_str(&mut self, field: i32, value: *const c_char) -> Result<(), Abort>;
    /// std::move of argument `index` of the argv array into the field (the
    /// entry becomes null)
    fn steal(&mut self, field: i32, index: c_int) -> Result<(), Abort>;
    fn push_option(&mut self, value: *const c_char) -> Result<(), Abort>;
    fn push_id(&mut self, id: i32) -> Result<(), Abort>;
    fn push_name(&mut self, value: *const c_char) -> Result<(), Abort>;
    /// ReportError: prints the message and marks the errors
    fn error(&mut self, msg: &CStr) -> Result<(), Abort>;
}

/// The parser's state the logic reads back.
struct State<'a> {
    sink: &'a mut dyn Sink,
    argc: c_int,
    argv: *mut *mut c_char,
    server_mode: bool,
    remote_client_mode: bool,
    client_operation: i32,
    match_mode: i32,
    print_usage: bool,
    print_version: bool,
    print_options: bool,
    edit_text: *const c_char,
}

fn eq(a: *const c_char, b: &CStr) -> bool {
    !a.is_null() && unsafe { strcasecmp(a, b.as_ptr()) } == 0
}

impl State<'_> {
    fn set(&mut self, field: i32, value: i32) -> Result<(), Abort> {
        match field {
            field::CLIENT_OPERATION => self.client_operation = value,
            field::MATCH_MODE => self.match_mode = value,
            field::SERVER_MODE => self.server_mode = value != 0,
            field::REMOTE_CLIENT_MODE => self.remote_client_mode = value != 0,
            field::PRINT_USAGE => self.print_usage = value != 0,
            field::PRINT_VERSION => self.print_version = value != 0,
            field::PRINT_OPTIONS => self.print_options = value != 0,
            _ => {}
        }
        self.sink.set_int(field, value)
    }

    /// argv[i] (it may have been moved out: null)
    fn arg(&self, i: c_int) -> *mut c_char {
        unsafe { *self.argv.add(i as usize) }
    }

    /// optind++ and the argument before it, or null past the end
    fn next_arg(&self) -> *mut c_char {
        unsafe {
            optind += 1;
            if optind > self.argc { std::ptr::null_mut() } else { self.arg(optind - 1) }
        }
    }

    /// optind++ for a required value: false (and an error) past the end
    fn take_value(&mut self, msg: &CStr) -> Result<bool, Abort> {
        unsafe {
            optind += 1;
            if optind > self.argc {
                self.sink.error(msg)?;
                return Ok(false);
            }
        }
        Ok(true)
    }

    fn steal(&mut self, field: i32) -> Result<(), Abort> {
        let i = unsafe { optind } - 1;
        self.sink.steal(field, i)?;
        if field == field::EDIT_QUEUE_TEXT {
            // the moved string, now held by the field (the entry is null)
            self.edit_text = std::ptr::null();
        }
        Ok(())
    }
}

/// The C++ "return" out of InitCommandLine (an error or -h/-v).
enum Flow {
    Next,
    Stop,
}

fn append(s: &mut State, c: c_int) -> Result<Flow, Abort> {
    let _ = c;
    s.set(field::CLIENT_OPERATION, op::DOWNLOAD)?;
    let err = c"Could not parse value of option 'A'";
    loop {
        let a = s.next_arg();
        unsafe { optarg = a };
        if eq(a, c"F") || eq(a, c"U") {
            // option ignored (but kept for compatibility)
        } else if eq(a, c"T") {
            s.set(field::ADD_TOP, 1)?;
        } else if eq(a, c"P") {
            s.set(field::ADD_PAUSED, 1)?;
        } else if eq(a, c"I") {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            let v = unsafe { atoi(s.arg(optind - 1)) };
            s.set(field::ADD_PRIORITY, v)?;
        } else if eq(a, c"C") {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            let v = s.arg(unsafe { optind } - 1);
            s.sink.set_str(field::ADD_CATEGORY, v)?;
        } else if eq(a, c"N") {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            s.steal(field::ADD_NZB_FILENAME)?;
        } else if eq(a, c"DK") {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            s.steal(field::ADD_DUPE_KEY)?;
        } else if eq(a, c"DS") {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            let v = unsafe { atoi(s.arg(optind - 1)) };
            s.set(field::ADD_DUPE_SCORE, v)?;
        } else if eq(a, c"DM") {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            let mode = s.arg(unsafe { optind } - 1);
            let m = if eq(mode, c"score") {
                0
            } else if eq(mode, c"all") {
                1
            } else if eq(mode, c"force") {
                2
            } else {
                s.sink.error(err)?;
                return Ok(Flow::Stop);
            };
            s.set(field::ADD_DUPE_MODE, m)?;
        } else {
            unsafe { optind -= 1 };
            return Ok(Flow::Next);
        }
    }
}

fn starts_dash(a: *const c_char) -> bool {
    a.is_null() || unsafe { *a } as u8 == b'-'
}

fn list(s: &mut State) -> Result<Flow, Abort> {
    let a = s.next_arg();
    unsafe { optarg = a };
    if starts_dash(a) {
        s.set(field::CLIENT_OPERATION, op::LIST_FILES)?;
        unsafe { optind -= 1 };
    } else if eq(a, c"F") || eq(a, c"FR") {
        s.set(field::CLIENT_OPERATION, op::LIST_FILES)?;
    } else if eq(a, c"G") || eq(a, c"GR") {
        s.set(field::CLIENT_OPERATION, op::LIST_GROUPS)?;
    } else if eq(a, c"O") {
        s.set(field::CLIENT_OPERATION, op::POST_QUEUE)?;
    } else if eq(a, c"S") {
        s.set(field::CLIENT_OPERATION, op::LIST_STATUS)?;
    } else if eq(a, c"H") {
        s.set(field::CLIENT_OPERATION, op::HISTORY)?;
    } else if eq(a, c"HA") {
        s.set(field::CLIENT_OPERATION, op::HISTORY_ALL)?;
    } else {
        s.sink.error(c"Could not parse value of option 'L'")?;
        return Ok(Flow::Stop);
    }
    if eq(a, c"FR") || eq(a, c"GR") {
        s.set(field::MATCH_MODE, 3)?;
        if !s.take_value(c"Could not parse value of option 'L'")? {
            return Ok(Flow::Stop);
        }
        s.steal(field::EDIT_QUEUE_TEXT)?;
    }
    Ok(Flow::Next)
}

fn pause(s: &mut State, c: u8) -> Result<Flow, Abort> {
    let a = s.next_arg();
    unsafe { optarg = a };
    let p = c == b'P';
    if starts_dash(a) || eq(a, c"D") {
        s.set(field::CLIENT_OPERATION, if p { op::DOWNLOAD_PAUSE } else { op::DOWNLOAD_UNPAUSE })?;
        if starts_dash(a) {
            unsafe { optind -= 1 };
        }
    } else if eq(a, c"O") {
        s.set(field::CLIENT_OPERATION, if p { op::POST_PAUSE } else { op::POST_UNPAUSE })?;
    } else if eq(a, c"S") {
        s.set(field::CLIENT_OPERATION, if p { op::SCAN_PAUSE } else { op::SCAN_UNPAUSE })?;
    } else {
        s.sink.error(if p { c"Could not parse value of option 'P'\n" } else { c"Could not parse value of option 'U'" })?;
        return Ok(Flow::Stop);
    }
    Ok(Flow::Next)
}

fn system(s: &mut State, arg: *mut c_char) -> Result<Flow, Abort> {
    let err = c"Could not parse value of option 'B'";
    if eq(arg, c"dump") {
        s.set(field::CLIENT_OPERATION, op::DUMP_DEBUG)?;
    } else if eq(arg, c"trace") {
        s.set(field::TEST_BACKTRACE, 1)?;
    } else if eq(arg, c"webget") {
        s.set(field::WEB_GET, 1)?;
        if !s.take_value(err)? {
            return Ok(Flow::Stop);
        }
        let v = s.arg(unsafe { optind } - 1);
        unsafe { optarg = v };
        s.sink.set_str(field::WEB_GET_FILENAME, v)?;
    } else if eq(arg, c"verify") {
        s.set(field::SIG_VERIFY, 1)?;
        for f in [field::PUB_KEY_FILENAME, field::SIG_FILENAME] {
            if !s.take_value(err)? {
                return Ok(Flow::Stop);
            }
            let v = s.arg(unsafe { optind } - 1);
            unsafe { optarg = v };
            s.sink.set_str(f, v)?;
        }
    } else {
        s.sink.error(err)?;
        return Ok(Flow::Stop);
    }
    Ok(Flow::Next)
}

fn edit_value(s: &mut State) -> Result<bool, Abort> {
    if !s.take_value(c"Could not parse value of option 'E'")? {
        return Ok(false);
    }
    // the text: read before the move (to check it), then held by the field
    let text = s.arg(unsafe { optind } - 1);
    s.steal(field::EDIT_QUEUE_TEXT)?;
    s.edit_text = text;
    Ok(true)
}

fn edit(s: &mut State, arg: *mut c_char) -> Result<Flow, Abort> {
    use edit::*;
    let err = c"Could not parse value of option 'E'";
    s.set(field::CLIENT_OPERATION, op::EDIT_QUEUE)?;
    let group = eq(arg, c"G") || eq(arg, c"GN") || eq(arg, c"GR");
    let file = eq(arg, c"F") || eq(arg, c"FN") || eq(arg, c"FR");
    let mode = if eq(arg, c"GN") || eq(arg, c"FN") {
        2
    } else if eq(arg, c"GR") || eq(arg, c"FR") {
        3
    } else {
        1
    };
    s.set(field::MATCH_MODE, mode)?;
    let post = eq(arg, c"O");
    let history = eq(arg, c"H");
    let mut a = arg;
    if group || file || post || history {
        if !s.take_value(err)? {
            return Ok(Flow::Stop);
        }
        a = s.arg(unsafe { optind } - 1);
        unsafe { optarg = a };
    }
    let has_eq = |t: *const c_char| !t.is_null() && unsafe { CStr::from_ptr(t) }.to_bytes().contains(&b'=');
    let pick = |g: i32, f: i32| if group { g } else { f };
    let action = if post {
        if eq(a, c"D") {
            POST_DELETE
        } else {
            s.sink.error(err)?;
            return Ok(Flow::Stop);
        }
    } else if history {
        if eq(a, c"D") {
            HISTORY_DELETE
        } else if eq(a, c"R") {
            HISTORY_RETURN
        } else if eq(a, c"P") {
            HISTORY_PROCESS
        } else if eq(a, c"A") {
            HISTORY_REDOWNLOAD
        } else if eq(a, c"F") {
            HISTORY_RETRY_FAILED
        } else if eq(a, c"O") {
            s.set(field::EDIT_ACTION, HISTORY_SET_PARAMETER)?;
            if !edit_value(s)? {
                return Ok(Flow::Stop);
            }
            if !has_eq(s.edit_text) {
                s.sink.error(err)?;
                return Ok(Flow::Stop);
            }
            return Ok(Flow::Next);
        } else if eq(a, c"B") {
            HISTORY_MARK_BAD
        } else if eq(a, c"G") {
            HISTORY_MARK_GOOD
        } else if eq(a, c"S") {
            HISTORY_MARK_SUCCESS
        } else {
            s.sink.error(err)?;
            return Ok(Flow::Stop);
        }
    } else if eq(a, c"T") {
        pick(GROUP_MOVE_TOP, FILE_MOVE_TOP)
    } else if eq(a, c"B") {
        pick(GROUP_MOVE_BOTTOM, FILE_MOVE_BOTTOM)
    } else if eq(a, c"P") {
        pick(GROUP_PAUSE, FILE_PAUSE)
    } else if eq(a, c"A") {
        pick(GROUP_PAUSE_ALL_PARS, FILE_PAUSE_ALL_PARS)
    } else if eq(a, c"R") {
        pick(GROUP_PAUSE_EXTRA_PARS, FILE_PAUSE_EXTRA_PARS)
    } else if eq(a, c"U") {
        pick(GROUP_RESUME, FILE_RESUME)
    } else if eq(a, c"D") {
        pick(GROUP_DELETE, FILE_DELETE)
    } else if eq(a, c"DP") {
        GROUP_PARK_DELETE
    } else if eq(a, c"SF") {
        GROUP_SORT_FILES
    } else if eq(a, c"C") || eq(a, c"K") || eq(a, c"CP") {
        // "K": compatibility with 0.8.0
        if !group {
            s.sink.error(c"Category can be set only for groups")?;
            return Ok(Flow::Stop);
        }
        s.set(field::EDIT_ACTION, if eq(a, c"CP") { GROUP_APPLY_CATEGORY } else { GROUP_SET_CATEGORY })?;
        return Ok(if edit_value(s)? { Flow::Next } else { Flow::Stop });
    } else if eq(a, c"N") {
        if !group {
            s.sink.error(c"Only groups can be renamed")?;
            return Ok(Flow::Stop);
        }
        s.set(field::EDIT_ACTION, GROUP_SET_NAME)?;
        return Ok(if edit_value(s)? { Flow::Next } else { Flow::Stop });
    } else if eq(a, c"M") {
        if !group {
            s.sink.error(c"Only groups can be merged")?;
            return Ok(Flow::Stop);
        }
        GROUP_MERGE
    } else if eq(a, c"S") {
        s.set(field::EDIT_ACTION, FILE_SPLIT)?;
        return Ok(if edit_value(s)? { Flow::Next } else { Flow::Stop });
    } else if eq(a, c"O") {
        if !group {
            s.sink.error(c"Post-process parameter can be set only for groups")?;
            return Ok(Flow::Stop);
        }
        s.set(field::EDIT_ACTION, GROUP_SET_PARAMETER)?;
        if !edit_value(s)? {
            return Ok(Flow::Stop);
        }
        if !has_eq(s.edit_text) {
            s.sink.error(err)?;
            return Ok(Flow::Stop);
        }
        return Ok(Flow::Next);
    } else if eq(a, c"I") {
        if !group {
            s.sink.error(c"Priority can be set only for groups")?;
            return Ok(Flow::Stop);
        }
        s.set(field::EDIT_ACTION, GROUP_SET_PRIORITY)?;
        if !edit_value(s)? {
            return Ok(Flow::Stop);
        }
        let t = s.edit_text;
        // atoi(text) == 0 && strcmp("0", text) (a null text read as empty)
        let zero = t.is_null() || unsafe { atoi(t) } == 0;
        let is_zero_text = !t.is_null() && unsafe { CStr::from_ptr(t) }.to_bytes() == b"0";
        if zero && !is_zero_text {
            s.sink.error(err)?;
            return Ok(Flow::Stop);
        }
        return Ok(Flow::Next);
    } else {
        let offset = if a.is_null() { 0 } else { unsafe { atoi(a) } };
        s.set(field::EDIT_OFFSET, offset)?;
        if offset == 0 {
            s.sink.error(err)?;
            return Ok(Flow::Stop);
        }
        pick(GROUP_MOVE_OFFSET, FILE_MOVE_OFFSET)
    };
    s.set(field::EDIT_ACTION, action)?;
    Ok(Flow::Next)
}

/// InitCommandLine
fn init_command_line(s: &mut State, use_long: bool) -> Result<(), Abort> {
    s.set(field::CLIENT_OPERATION, op::NONE)?;
    unsafe { optind = 0 };
    loop {
        let c = unsafe {
            if use_long {
                s.sink.getopt_long(s.argc, s.argv)
            } else {
                getopt(s.argc, s.argv, SHORT_OPTIONS.as_ptr())
            }
        };
        if c == -1 {
            break;
        }
        let arg = unsafe { optarg };
        let flow = match c as u8 {
            b'c' => {
                s.sink.set_str(field::CONFIG_FILENAME, arg)?;
                Flow::Next
            }
            b'n' => {
                s.sink.set_str(field::CONFIG_FILENAME, std::ptr::null())?;
                s.set(field::NO_CONFIG, 1)?;
                Flow::Next
            }
            b'h' => {
                s.set(field::PRINT_USAGE, 1)?;
                Flow::Stop
            }
            b'v' => {
                s.set(field::PRINT_VERSION, 1)?;
                Flow::Stop
            }
            b'p' => {
                s.set(field::PRINT_OPTIONS, 1)?;
                Flow::Next
            }
            b'o' => {
                s.sink.push_option(arg)?;
                Flow::Next
            }
            b's' => {
                s.set(field::SERVER_MODE, 1)?;
                Flow::Next
            }
            b'D' => {
                s.set(field::SERVER_MODE, 1)?;
                s.set(field::DAEMON_MODE, 1)?;
                Flow::Next
            }
            b'A' => append(s, c)?,
            b'L' => list(s)?,
            b'P' | b'U' => pause(s, c as u8)?,
            b'R' => {
                s.set(field::CLIENT_OPERATION, op::SET_RATE)?;
                // C++'s out-of-range float-to-int behavior depends on the host
                // compiler/architecture. Do not impose x86 results on ARM.
                s.sink.set_str(field::SET_RATE_ARG, arg)?;
                Flow::Next
            }
            b'B' => system(s, arg)?,
            b'G' => {
                s.set(field::CLIENT_OPERATION, op::LOG)?;
                let v = unsafe { atoi(arg) };
                s.set(field::LOG_LINES, v)?;
                if v == 0 {
                    s.sink.error(c"Could not parse value of option 'G'")?;
                    Flow::Stop
                } else {
                    Flow::Next
                }
            }
            b'T' => {
                s.set(field::ADD_TOP, 1)?;
                Flow::Next
            }
            b'C' => {
                s.set(field::REMOTE_CLIENT_MODE, 1)?;
                Flow::Next
            }
            b'E' => edit(s, arg)?,
            b'Q' => {
                s.set(field::CLIENT_OPERATION, op::SHUTDOWN)?;
                Flow::Next
            }
            b'O' => {
                s.set(field::CLIENT_OPERATION, op::RELOAD)?;
                Flow::Next
            }
            b'V' => {
                s.set(field::CLIENT_OPERATION, op::VERSION)?;
                Flow::Next
            }
            b'W' => {
                s.set(field::CLIENT_OPERATION, op::WRITE_LOG)?;
                let kind = [c"I", c"W", c"E", c"D", c"G"].iter().position(|k| eq(arg, k));
                match kind {
                    Some(k) => {
                        s.set(field::WRITE_LOG_KIND, k as i32)?;
                        Flow::Next
                    }
                    None => {
                        s.sink.error(c"Could not parse value of option 'W'")?;
                        Flow::Stop
                    }
                }
            }
            b'K' => {
                // "K": compatibility with 0.8.0
                s.sink.set_str(field::ADD_CATEGORY, arg)?;
                Flow::Next
            }
            b'S' => {
                let a = s.next_arg();
                unsafe { optarg = a };
                if starts_dash(a) {
                    s.set(field::CLIENT_OPERATION, op::SCAN_ASYNC)?;
                    unsafe { optind -= 1 };
                    Flow::Next
                } else if eq(a, c"W") {
                    s.set(field::CLIENT_OPERATION, op::SCAN_SYNC)?;
                    Flow::Next
                } else {
                    s.sink.error(c"Could not parse value of option 'S'")?;
                    Flow::Stop
                }
            }
            b'?' => {
                s.set(field::ERRORS, 1)?;
                Flow::Stop
            }
            _ => Flow::Next,
        };
        if let Flow::Stop = flow {
            return Ok(());
        }
    }
    if s.server_mode && s.client_operation == op::DOWNLOAD_PAUSE {
        s.set(field::PAUSE_DOWNLOAD, 1)?;
        s.set(field::CLIENT_OPERATION, op::NONE)?;
    }
    Ok(())
}

/// strtok(list, ", ") tokens of a C string
fn tokens(s: &[u8]) -> impl Iterator<Item = &[u8]> {
    s.split(|&b| b == b',' || b == b' ').filter(|t| !t.is_empty())
}

fn atoi_bytes(b: &[u8]) -> i32 {
    let mut v = b.to_vec();
    v.push(0);
    unsafe { atoi(v.as_ptr().cast()) }
}

/// ParseFileIdList
fn file_id_list(s: &mut State, from: c_int) -> Result<(), Abort> {
    for i in from..s.argc {
        let a = s.arg(i);
        // a moved-out argument is a null CString: strtok finds nothing in it
        let text = if a.is_null() { &b""[..] } else { unsafe { CStr::from_ptr(a) }.to_bytes() };
        for t in tokens(text) {
            let (from_id, to_id) = match t.iter().position(|&b| b == b'-') {
                Some(dash) => {
                    // BString<100>::Set(t, dash): up to 99 bytes, all of them for 0
                    let len = if dash > 0 { dash.min(99) } else { 99 };
                    let a = atoi_bytes(&t[..len.min(t.len())]);
                    let b = atoi_bytes(&t[dash + 1..]);
                    if a <= 0 || b <= 0 {
                        s.sink.error(c"invalid list of file IDs")?;
                        return Ok(());
                    }
                    (a, b)
                }
                None => {
                    let a = atoi_bytes(t);
                    if a <= 0 {
                        s.sink.error(c"invalid list of file IDs")?;
                        return Ok(());
                    }
                    (a, a)
                }
            };
            let count = if from_id < to_id { to_id - from_id + 1 } else { from_id - to_id + 1 };
            for k in 0..count {
                s.sink.push_id(if from_id < to_id { from_id + k } else { from_id - k })?;
            }
        }
    }
    Ok(())
}

/// InitFileArg
fn init_file_arg(s: &mut State) -> Result<(), Abort> {
    let idx = unsafe { optind };
    let client_ok = |op: i32| op == op::NONE || op == op::DOWNLOAD || op == op::WRITE_LOG;
    if idx >= s.argc {
        if !s.server_mode && !s.remote_client_mode && client_ok(s.client_operation) {
            s.sink.error(if s.client_operation == op::WRITE_LOG { c"Log-text not specified" } else { c"Nzb-file or Url not specified" })?;
        }
    } else if s.client_operation == op::EDIT_QUEUE {
        if s.match_mode == 1 {
            file_id_list(s, idx)?;
        } else {
            for i in idx..s.argc {
                let a = s.arg(i);
                s.sink.push_name(a)?;
            }
        }
    } else {
        let a = s.arg(idx);
        s.sink.set_str(field::LAST_ARG, a)?;
        // a moved-out argument (null) read as empty
        let name: &CStr = if a.is_null() { c"" } else { unsafe { CStr::from_ptr(a) } };
        let absolute = name.to_bytes().first() == Some(&b'/')
            || unsafe { strncasecmp(name.as_ptr(), c"http://".as_ptr(), 6) } == 0
            || unsafe { strncasecmp(name.as_ptr(), c"https://".as_ptr(), 7) } == 0;
        if absolute {
            s.sink.set_str(field::ARG_FILENAME, name.as_ptr())?;
        } else {
            let mut buf = vec![0u8; 1024];
            let cwd = unsafe { getcwd(buf.as_mut_ptr().cast(), buf.len()) };
            if cwd.is_null() {
                buf[0] = 0;
            }
            let mut path = CStr::from_bytes_until_nul(&buf).map(|c| c.to_bytes().to_vec()).unwrap_or_default();
            path.push(b'/');
            path.extend_from_slice(name.to_bytes());
            path.push(0);
            s.sink.set_str(field::ARG_FILENAME, path.as_ptr().cast())?;
        }
        if s.server_mode || s.remote_client_mode || !client_ok(s.client_operation) {
            s.sink.error(c"Too many arguments")?;
        }
    }
    Ok(())
}

/// CommandLineParser's constructor over `argv` (argc entries, permuted in
/// place by getopt).
///
/// # Safety
/// `argv` has `argc` non-null C strings followed by a null sentinel. The sink
/// may move entries already consumed by getopt, nulling them and retaining
/// their strings until the destination is overwritten or parsing finishes.
/// Callbacks must preserve unread arguments; getopt globals are exclusive.
pub unsafe fn parse(argc: c_int, argv: *mut *mut c_char, use_long: bool, sink: &mut dyn Sink) -> Result<(), Abort> {
    let mut s = State {
        sink,
        argc,
        argv,
        server_mode: false,
        remote_client_mode: false,
        client_operation: op::NONE,
        match_mode: 1,
        print_usage: false,
        print_version: false,
        print_options: false,
        edit_text: std::ptr::null(),
    };
    init_command_line(&mut s, use_long)?;
    if argc == 1 {
        s.set(field::PRINT_USAGE, 1)?;
        return Ok(());
    }
    if !s.print_options && !s.print_usage && !s.print_version {
        init_file_arg(&mut s)?;
    }
    Ok(())
}
