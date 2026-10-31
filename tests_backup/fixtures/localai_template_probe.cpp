// CPU-only exercise of the matching private server, template engine and parser.
#include "arg.h"
#include "chat.h"
#include "chat-auto-parser.h"
#include "chat-peg-parser.h"
#include "llama-grammar.h"
#include "server-common.h"
#include "server-chat.h"
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

// Compile the same differential fixture against V1 JSON preparation and V2 typed preparation.
static common_json prepared_data(const common_json & result) { return result; }
template <typename T> static common_json prepared_data(const T & result) { return result.params; }
static void prepared_apply(const common_json &, common_chat_parser_params &) {}
template <typename T> static void prepared_apply(const T & result, common_chat_parser_params & target) {
    result.apply_chat_parser(target);
}

static server_task_result_cmpl_final final_result(const common_json & test, const std::string & raw, bool stream) {
    server_task_result_cmpl_final result{};
    result.stream = stream;
    result.stop = test.value("stop", test.value("stop_limit", false) ? "limit" : "eos") == "limit" ? STOP_TYPE_LIMIT :
                  test.value("stop", "eos") == "word" ? STOP_TYPE_WORD : STOP_TYPE_EOS;
    result.content = stream ? "" : raw;
#ifdef COMMON_CHAT_HAS_PROTOCOL_EVIDENCE
    result.protocol_input = raw;
    result.raw_generated_text = test.value("raw_sampled", raw);
    result.stop_cause = server_stop_cause_from_string(test.value("cause", "unknown"));
    result.context_shifted = test.value("context_shifted", false);
    result.truncated = test.value("truncated", false);
#endif
    return result;
}

static common_json error_json(const std::exception & error) {
#ifdef COMMON_CHAT_HAS_PROTOCOL_EVIDENCE
    if (auto protocol = dynamic_cast<const common_chat_protocol_error *>(&error)) {
        return protocol->response_error();
    }
#endif
    return format_error_response(error.what(), ERROR_TYPE_SERVER);
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
        const auto endpoint = test.value("endpoint", "chat");
        if (endpoint == "responses") { body = server_chat_convert_responses_to_chatcmpl(body); }
        if (endpoint == "anthropic") { body = server_chat_convert_anthropic_to_oai(body); }
        if (endpoint == "transcriptions") {
            std::map<std::string, uploaded_file> uploads;
            uploads["file"].data = {0};
            std::vector<raw_buffer> audio_files;
            body = convert_transcriptions_to_chatcmpl(body, options.tmpls.get(), uploads, audio_files);
        }
        auto original_body = body;
        out["converted_request"] = original_body;
        std::vector<raw_buffer> files;
        using prepared_type = decltype(oaicompat_chat_params_parse(body, options, files));
        std::optional<prepared_type> prepared;
        common_json native;
        if (test.value("raw_endpoint", false)) { native = body; }
        else { prepared = oaicompat_chat_params_parse(body, options, files); native = prepared_data(*prepared); }
        out["generation_prompt"] = native.value("generation_prompt", "");
        out["public_private_control"] = native.contains("no_action_tool_name");
        out["caller_request_unchanged"] = body == original_body;
        out["caller_request_after"] = body;
        out["caller_menu_unchanged"] = body.value("tools", common_json()) == original_body.value("tools", common_json());
        out["prompt"] = native.at("prompt");
        out["grammar"] = native.value("grammar", "");
        out["parser"] = native.value("chat_parser", "");
        out["grammar_lazy"] = native.value("grammar_lazy", false);
        out["grammar_triggers"] = native.value("grammar_triggers", common_json::array());
        // Token metadata requires a model vocabulary; parser tests use bytes only.
        for (const auto * key : {"message_delimiters", "preserved_tokens", "grammar_triggers",
                                "reasoning_budget_start_tag", "reasoning_budget_end_tags", "reasoning_budget_message"}) {
            native.erase(key);
        }
        auto params = server_schema::eval_llama_cmpl_schema(nullptr, base, {}, native);
        if (prepared) { prepared_apply(*prepared, params.chat_parser_params); }
        out["active_name"] = params.chat_parser_params.no_action_tool_name;
        if (test.contains("grammar_output") && !out.at("grammar").get<std::string>().empty()) {
            const auto grammar_input = native.value("grammar_lazy", false) ? test.at("grammar_output").get<std::string>() :
                native.value("generation_prompt", "") + test.at("grammar_output").get<std::string>();
            out["grammar_accepts"] = grammar_accepts(out.at("grammar"), grammar_input);
        }
        std::string raw = test.value("output", "");
        if (test.contains("output_hex")) {
            const auto bytes = test.at("output_hex").get<std::string>();
            raw.clear();
            for (size_t i = 0; i < bytes.size(); i += 2) {
                raw += char(std::stoul(bytes.substr(i, 2), nullptr, 16));
            }
        }
        out["raw_hex"] = hex_bytes(raw);
        out["raw"] = raw;
        task_result_state buffered(params.chat_parser_params);
        std::vector<common_chat_msg_diff> diffs;
        try {
            auto final = final_result(test, raw, false);
            common_chat_msg msg;
            if (test.value("final_owner", false)) {
                final.update(buffered);
                msg = final.oaicompat_msg;
            } else { msg = buffered.update_chat_msg(raw, false, diffs); }
            auto parsed_message = message_json(msg);
            for (const auto & item : parsed_message.items()) { out[item.key()] = item.value(); }
            out["complete_parse"] = true;
            out["ids"] = buffered.generated_tool_call_ids;
            if (!test.value("final_owner", false)) {
                final.oaicompat_msg = msg;
                final.oaicompat_msg_diffs = diffs;
            }
            out["buffered_wire"] = final.to_json_oaicompat_chat();
            out["buffered_responses_wire"] = final.to_json_oaicompat_resp();
            out["stream_final_wire"] = final.to_json_oaicompat_chat_stream();
        } catch (const std::exception & error) {
            out["complete_parse"] = false;
            out["parse_error"] = error.what();
            out["error_wire"] = error_json(error);
        }
        if (test.value("prefixes", false)) {
            task_result_state streamed(params.chat_parser_params);
            common_json prefixes = common_json::array();
            bool failed = false;
            const size_t published = test.value("published_bytes", raw.size());
            for (size_t i = 0; i <= published; ++i) {
                common_json prefix = {{"bytes", i}};
                try {
                    auto previous = streamed.chat_msg;
                    server_task_result_cmpl_partial chunk;
                    chunk.n_decoded = i;
                    chunk.content = i == 0 ? "" : raw.substr(i - 1, 1);
                    chunk.update(streamed);
                    auto msg = streamed.chat_msg;
                    diffs = chunk.oaicompat_msg_diffs;
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
                    auto partial_wire = chunk.to_json_oaicompat_chat();
                    prefix["partial_wire"] = partial_wire;
                    for (const auto & event : partial_wire) {
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
                    auto final = final_result(test, raw, true);
                    common_chat_msg msg;
                    if (test.value("final_owner", false)) {
                        final.update(streamed);
                        msg = final.oaicompat_msg;
                    } else { msg = streamed.update_chat_msg("", false, diffs); }
                    out["streamed"] = message_json(msg);
                    if (!test.value("final_owner", false)) {
                        final.oaicompat_msg = msg;
                        final.oaicompat_msg_diffs = diffs;
                    }
                    out["streamed_final_wire"] = final.to_json_oaicompat_chat_stream();
                    out["streamed_final_responses_wire"] = final.to_json_oaicompat_resp_stream();
                } catch (const std::exception & error) {
                    out["stream_error"] = error.what(); out["stream_error_wire"] = error_json(error);
                }
            }
        }
    } catch (const std::invalid_argument & error) {
        out["request_error"] = error.what();
        out["request_error_wire"] = format_error_response(error.what(), ERROR_TYPE_INVALID_REQUEST);
    } catch (const common_json_error & error) {
        out["request_error"] = error.what();
        out["request_error_wire"] = format_error_response(error.what(), ERROR_TYPE_INVALID_REQUEST);
    } catch (const std::exception & error) { out["request_error"] = error.what(); }
    std::cout << out.dump_safe() << '\n';
}
