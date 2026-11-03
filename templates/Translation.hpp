#pragma once

namespace reframework::translation {
    void startup();
    const char* translate(const char* text, const char* textEnd = nullptr);
}

inline const char* REF_ImGui_TranslateCB(const char* text, const char* textEnd) {
    return reframework::translation::translate(text, textEnd);
}
