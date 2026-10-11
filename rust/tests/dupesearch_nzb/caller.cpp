// Same-binary comparison of the independent C++ source and real Rust-enabled caller.
#include "reference.inc"
#include "candidate.inc"
#include "xml.inc"
#include <chrono>
#include <random>
#include <iostream>
#include <cstdlib>
#include <clocale>
#include <fstream>

void Require(bool ok, const char* detail) { if (!ok) { std::cerr << detail << '\n'; std::exit(1); } }
bool Equal(const NzbSummary& a, const NzbSummary& b) {
    if (a.files != b.files || a.totalBytes != b.totalBytes || a.filenames != b.filenames ||
        a.poster != b.poster || a.messageIds != b.messageIds || a.groups != b.groups ||
        a.meta != b.meta || a.mainName != b.mainName || a.dataBytes != b.dataBytes ||
        a.dataFiles != b.dataFiles || a.heads.size() != b.heads.size() || a.Fingerprint() != b.Fingerprint()) return false;
    for (size_t i = 0; i < a.heads.size(); ++i)
        if (a.heads[i].name != b.heads[i].name || a.heads[i].messageId != b.heads[i].messageId || a.heads[i].bytes != b.heads[i].bytes) return false;
    return true;
}
std::string Fixture(int files, int parts, bool quoted, bool parOnly = false) {
    std::string xml = "<nzb xmlns='http://www.newzbin.com/DTD/2003/nzb'><head><meta type='IMDB'> tt123 </meta></head>";
    for (int f = 0; f < files; ++f) {
        std::string name = "release.part" + std::to_string(f) + ((parOnly || f % 7 == 6) ? ".par2" : ".rar");
        xml += "<file poster='p' subject='" + (quoted ? "&quot;" + name + "&quot;" : name) + " yEnc (1/100)'><groups><group> alt.binaries.test </group></groups><segments>";
        for (int p = 1; p <= parts; ++p) xml += "<segment bytes='768000' number='" + std::to_string(p) + "'>id" + std::to_string(f) + "." + std::to_string(p) + "@host</segment>";
        xml += "</segments></file>";
    }
    return xml + "</nzb>";
}
void Compare(const std::string& xml) {
    NzbSummary a, b;
    bool x = ReferenceParse(xml, a), y = NzbReader::Parse(xml, b);
    Require(x == y && Equal(a,b), "full summary differs");
}
int main(int argc, char** argv) {
    std::mt19937 rng(731921);
    if (argc > 1 && std::string(argv[1]) == "bench") {
        volatile uint64_t sink = 0;
        for (bool quoted : {true, false}) for (auto [files, parts, parOnly] : {std::tuple{1,1,false}, {1,1,true}, {30,10,false}, {100,100,false}}) {
            auto xml = Fixture(files, parts, quoted, parOnly); Compare(xml);
            for (int warm = 0; warm < 8; ++warm) Compare(xml);
            int loops = files == 100 ? 25 : files == 30 ? 500 : 20000;
            for (int round = 0; round < 15; ++round) for (int slot = 0; slot < 2; ++slot) {
                bool rust = ((round + slot) % 2) != 0;
                auto start = std::chrono::steady_clock::now();
                uint64_t sum = 0;
                for (int i = 0; i < loops; ++i) { NzbSummary info; bool ok = rust ? NzbReader::Parse(xml,info) : ReferenceParse(xml,info); sum += ok + info.totalBytes + info.messageIds.size() + info.dataBytes + info.mainName.size(); }
                auto elapsed = std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/loops;
                sink = sum;
                std::cout << ((quoted ? "quoted" : "unquoted") + std::string(parOnly ? "-par" : "")) << ',' << files << ',' << parts << ',' << round << ',' << (rust ? "rust" : "cpp") << ',' << elapsed << ',' << sum << '\n';
            }
        }
        return sink == 0;
    }
    size_t helperCases = 0;
    size_t localeCount = 0;
    for (const char* locale : {"C", "C.UTF-8", "en_US.ISO8859-1", "tr_TR.ISO8859-9", "en_US.UTF-8"}) {
        Require(std::setlocale(LC_ALL,locale) != nullptr, (std::string("required locale unavailable: ")+locale).c_str());
        ++localeCount;
        std::cout << "locale " << locale << '\n';
        for (int n=0;n<25000;++n) {
            std::string bytes(rng()%600,' '); for (char& ch: bytes) ch = (char)(rng()%256);
            Require(ReferenceNameOfSubject(bytes)==NameOfSubject(bytes),"subject differs");
            Require(ReferenceIsParName(bytes)==IsParName(bytes),"PAR name differs");
            ++helperCases;
        }
        for (int n=0;n<15000;++n) {
            std::string s(rng()%80,'a');
            const std::string suffixes[]={" yEnc", " YENC (1/20)", "\vyEnc\f(01/2)\r\n", " yEnc (1/)", " yEnc(1/2)", " yEnc (1/2) x", "\t\tyenc\t", std::string(" yEnc (1/2)\0tail", 16)};
            Require(suffixes[7].size() == 16, "embedded NUL fixture was truncated");
            s += suffixes[rng()%8];
            if(n%4==0) s="prefix \" "+s+" \" extra";
            if(n%4==1) s="\"\" "+s;
            Require(ReferenceNameOfSubject(s)==NameOfSubject(s),"generated subject differs"); ++helperCases;
        }
        for (auto name : {"a.par2", "a.PAR2", "prefix \" x \" yEnc (1/2)", "a yEnc (1/2)", "a yEnc", "a yEnc (1/)", "\"\" a yEnc", "a\vyEnc\f(1/2)\t"}) {
            Require(ReferenceNameOfSubject(name)==NameOfSubject(name),"targeted subject differs");
            Require(ReferenceIsParName(name)==IsParName(name),"targeted PAR differs");
        }
        // Every byte at every position catches bracket-edge, whitespace and ctype changes.
        for (int pos=0;pos<6;++pos) for (int byte=0;byte<256;++byte) {
            std::string s="a.par2"; s[pos]=(char)byte;
            Require(ReferenceIsParName(s)==IsParName(s),"PAR byte differs");
        }
    }
    Require(localeCount == 5 && helperCases == 200000, "locale/helper coverage incomplete");
    Require(std::setlocale(LC_ALL,"C") != nullptr, "C locale unavailable");
    std::vector<std::string> fixtures = {"", "<nzb/>", "<nzb><file", Fixture(1,1,false), Fixture(30,10,true),
        "<n:nzb xmlns:n='urn:x'><n:file poster='p' subject='&quot;a.rar&quot;'><n:segments><n:segment bytes='1' number='1'><![CDATA[<x@y>]]></n:segment></n:segments></n:file></n:nzb>",
        "<!DOCTYPE nzb [<!ENTITY x 'id'>]><nzb><file subject='a'><segments><segment bytes='1'>&x;</segment></segments></file></nzb>"};
    for (const auto& xml:fixtures) Compare(xml);
    auto seed=Fixture(3,4,false);
    for (int n=0;n<3000;++n) { auto xml=seed; size_t pos=rng()%xml.size(); if(n%3==0) xml.resize(pos); else if(n%3==1) xml[pos]=(char)(rng()%256); else xml.insert(pos,1,(char)(rng()%256)); Compare(xml); }
    if (argc > 1) for (int i=1;i<argc;++i) {
        try {
            std::ifstream f(argv[i],std::ios::binary);
            Require(f.is_open(), (std::string("cannot open fixture: ")+argv[i]).c_str());
            auto xml = std::string(std::istreambuf_iterator<char>(f),{});
            Require(!f.bad(), (std::string("cannot read fixture: ")+argv[i]).c_str());
            Compare(xml);
        } catch (const std::exception& e) {
            std::cerr << "cannot read fixture " << argv[i] << ": " << e.what() << '\n'; return 1;
        }
    }
    std::cout << "PASS " << helperCases << " random helper cases; 3007 XML summaries plus fixtures; all summary fields observed\n";
}
