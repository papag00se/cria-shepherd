// CPU-only exercise of the matching private server, template engine and parser.
#include "arg.h"
#include "chat.h"
#include "llama-grammar.h"
#include "server-common.h"
#include "server-schema.h"
#include "server-task.h"
#include <fstream>
#include <iostream>
#include <sstream>

static std::string read_file_text(const std::string & path) {
    std::ifstream file(path);
    if (!file) { throw std::runtime_error("Cannot read " + path); }
    std::stringstream text; text << file.rdbuf(); return text.str();
}

static std::string hex_bytes(const std::string & text) {
    static const char hex[] = "0123456789abcdef";
    std::string result;
    for (unsigned char byte : text) { result += hex[byte >> 4]; result += hex[byte & 15]; }
    return result;
}

static common_json message_json(const common_chat_msg & msg) {
    common_json calls = common_json::array();
    for (const auto & call : msg.tool_calls) {
        calls.push_back({{"name", call.name}, {"arguments_raw", call.arguments}, {"arguments_hex", hex_bytes(call.arguments)}, {"id", call.id}});
    }
    return {{"calls", calls}, {"content", msg.content}, {"reasoning", msg.reasoning_content}};
}

static bool grammar_accepts(const std::string & grammar_text, const std::string & text) {
    auto grammar = std::unique_ptr<llama_grammar, decltype(&llama_grammar_free_impl)>(
        llama_grammar_init_impl(nullptr, grammar_text.c_str(), "root", false, nullptr, 0, nullptr, 0),
        llama_grammar_free_impl);
    if (!grammar) { throw std::runtime_error("Cannot build grammar"); }
    try { llama_grammar_accept_str(*grammar, text); }
    catch (const std::runtime_error &) { return false; }
    for (const auto & stack : llama_grammar_get_stacks(grammar.get())) {
        if (stack.empty()) { return true; }
    }
    return false;
}

int main(int argc, char ** argv) {
    common_json out = common_json::object();
    try {
        std::stringstream text; text << std::cin.rdbuf();
        auto test = common_json::parse(text.str());
        common_params base;
        if (argc > 2 && std::string(argv[2]) != "-") {
            char * options[] = {argv[0], const_cast<char *>("--no-action-tool"), argv[2]};
            if (!common_params_parse(3, options, base, LLAMA_EXAMPLE_SERVER)) {
                throw std::runtime_error("Invalid --no-action-tool file");
            }
        }
        server_chat_params options{};
        options.use_jinja = true;
        options.prefill_assistant = false;
        options.enable_thinking = true;
        options.reasoning_format = COMMON_REASONING_FORMAT_DEEPSEEK;
        options.no_action_tool = base.no_action_tool;
        options.tmpls = common_chat_templates_init(nullptr, read_file_text(argv[1]), "<|endoftext|>", "<|im_end|>");
        auto body = test.at("request");
        auto original_body = body;
        std::vector<raw_buffer> files;
        auto native = oaicompat_chat_params_parse(body, options, files);
        out["caller_menu_unchanged"] = body.value("tools", common_json()) == original_body.value("tools", common_json());
        out["prompt"] = native.at("prompt");
        out["grammar"] = native.value("grammar", "");
        out["parser"] = native.at("chat_parser");
        out["active_name"] = native.value("no_action_tool_name", "");
        out["grammar_lazy"] = native.value("grammar_lazy", false);
        out["grammar_triggers"] = native.at("grammar_triggers");
        // Token metadata requires a model vocabulary; parser tests use bytes only.
        for (const auto * key : {"message_delimiters", "preserved_tokens", "grammar_triggers",
                                "reasoning_budget_start_tag", "reasoning_budget_end_tags", "reasoning_budget_message"}) {
            native.erase(key);
        }
        auto params = server_schema::eval_llama_cmpl_schema(nullptr, base, {}, native);
        if (test.contains("grammar_output") && !out.at("grammar").get<std::string>().empty()) {
            out["grammar_accepts"] = grammar_accepts(out.at("grammar"), test.at("grammar_output"));
        }
        const auto raw = test.value("output", "");
        out["raw"] = raw;
        task_result_state buffered(params.chat_parser_params);
        std::vector<common_chat_msg_diff> diffs;
        try {
            auto msg = buffered.update_chat_msg(raw, false, diffs);
            auto parsed_message = message_json(msg);
            for (const auto & item : parsed_message.items()) { out[item.key()] = item.value(); }
            out["complete_parse"] = true;
            out["ids"] = buffered.generated_tool_call_ids;
            server_task_result_cmpl_final final;
            final.stop = STOP_TYPE_EOS;
            final.oaicompat_msg = msg;
            final.oaicompat_msg_diffs = diffs;
            out["buffered_wire"] = final.to_json_oaicompat_chat();
            out["stream_final_wire"] = final.to_json_oaicompat_chat_stream();
        } catch (const std::exception & error) {
            out["complete_parse"] = false;
            out["parse_error"] = error.what();
        }
        if (test.value("prefixes", false)) {
            task_result_state streamed(params.chat_parser_params);
            common_json prefixes = common_json::array();
            bool failed = false;
            for (size_t i = 0; i <= raw.size(); ++i) {
                common_json prefix = {{"bytes", i}};
                try {
                    auto previous = streamed.chat_msg;
                    auto msg = streamed.update_chat_msg(i == 0 ? "" : raw.substr(i - 1, 1), true, diffs);
                    // Exercise the native differ independently as well as the server's actual path.
                    auto checked = common_chat_msg_diff::compute_diffs(previous, msg);
                    std::string content_delta;
                    common_json wire = common_json::array();
                    common_json argument_deltas = common_json::array();
                    for (const auto & diff : checked) {
                        content_delta += diff.content_delta;
                        if (diff.tool_call_index != std::string::npos) {
                            argument_deltas.push_back({{"index", diff.tool_call_index}, {"hex", hex_bytes(diff.tool_call_delta.arguments)}});
                        }

                    }
                    auto parsed_message = message_json(msg);
                    for (const auto & item : parsed_message.items()) { prefix[item.key()] = item.value(); }
                    server_task_result_cmpl_final chunk;
                    chunk.oaicompat_msg = msg;
                    chunk.oaicompat_msg_diffs = checked;
                    for (const auto & event : chunk.to_json_oaicompat_chat_stream()) {
                        wire.push_back(event.at("choices").at(0).at("delta"));
                    }
                    prefix["deltas"] = wire;
                    prefix["argument_deltas"] = argument_deltas;
                    prefix["append_only"] = previous.content + content_delta == msg.content &&
                        msg.content.compare(0, previous.content.size(), previous.content) == 0;
                    prefix["nondecreasing_calls"] = msg.tool_calls.size() >= previous.tool_calls.size();
                    prefix["ids"] = streamed.generated_tool_call_ids;
                } catch (const std::exception & error) {
                    prefix["error"] = error.what();
                    failed = true;
                }
                prefixes.push_back(prefix);
                if (failed) { break; }
            }
            out["prefixes"] = prefixes;
            if (!failed) {
                try {
                    auto msg = streamed.update_chat_msg("", false, diffs);
                    out["streamed"] = message_json(msg);
                    server_task_result_cmpl_final final;
                    final.stop = STOP_TYPE_EOS;
                    final.oaicompat_msg = msg;
                    final.oaicompat_msg_diffs = diffs;
                    out["streamed_final_wire"] = final.to_json_oaicompat_chat_stream();
                } catch (const std::exception & error) { out["stream_error"] = error.what(); }
            }
        }
    } catch (const std::exception & error) { out["request_error"] = error.what(); }
    std::cout << out.dump_safe() << '\n';
}
