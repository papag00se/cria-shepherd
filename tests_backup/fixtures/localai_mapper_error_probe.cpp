// CPU-only comparison of ordinary mapper exception identity.
#include "chat.h"
#include "chat-peg-parser.h"
#include <iostream>
#include <typeinfo>

static common_json exception_json(const std::exception & error) {
    return {{"type", typeid(error).name()}, {"message", error.what()}};
}

int main() {
    const std::string raw = "<call>read_file" + std::string(1, char(0xff)) + "</arg>";
    auto parser = build_chat_peg_parser([](common_chat_peg_builder & p) {
        return p.tool_open(p.literal("<call>")) + p.tool_name(p.literal("read_file")) +
               p.tool_arg_name(p.until("</arg>")) + p.literal("</arg>") + p.end();
    });
    common_json out;
    common_peg_parse_context context(raw, COMMON_PEG_PARSE_FLAG_LENIENT);
    auto result = parser.parse(context);
    common_chat_msg message;
    common_chat_peg_mapper mapper(message);
    try { mapper.from_ast(context.ast, result); }
    catch (const std::exception & error) { out["ordinary_mapper"] = exception_json(error); }
    for (bool partial : {false, true}) {
        try { common_chat_peg_parse(parser, raw, partial, {}); }
        catch (const std::exception & error) {
            out[partial ? "partial_parse" : "final_parse"] = exception_json(error);
        }
    }
    std::cout << out.dump_safe() << '\n';
}
