<?php
/**
 * Meta-box HTML template.
 * Variables available from DRGR_SEO_Manager::meta_box_callback():
 *   $post, $seo_title, $seo_desc, $og_title, $og_desc, $tw_title, $tw_desc,
 *   $disable_yoast, $var_meta
 */
if ( ! defined( 'ABSPATH' ) ) exit;

/**
 * Helper: render a variations list for one field.
 *
 * @param string $list_id       DOM id of the wrapper div.
 * @param string $field_name    HTML name attribute for the input array.
 * @param string $radio_name    HTML name attribute for the active-index radio group.
 * @param array  $items         Variation strings.
 * @param int    $active_index  Currently selected variation index.
 * @param bool   $is_textarea   Whether to render <textarea> instead of <input type="text">.
 */
function drgr_render_variations( $list_id, $field_name, $radio_name, $items, $active_index, $is_textarea = false ) {
    echo '<div id="' . esc_attr( $list_id ) . '" class="drgr-variations-list">';
    foreach ( $items as $i => $val ) {
        echo '<div class="drgr-variation-row">';
        echo '<input type="radio" name="' . esc_attr( $radio_name ) . '" value="' . (int) $i . '" title="' . esc_attr__( 'Use this variation', 'drgr-seo' ) . '" ' . checked( $active_index, $i, false ) . '>';
        if ( $is_textarea ) {
            echo '<textarea name="' . esc_attr( $field_name ) . '[]" class="large-text" rows="2">' . esc_textarea( $val ) . '</textarea>';
        } else {
            echo '<input type="text" name="' . esc_attr( $field_name ) . '[]" value="' . esc_attr( $val ) . '" class="large-text">';
        }
        echo '<button type="button" class="button drgr-btn-rm-var" data-list="' . esc_attr( $list_id ) . '" aria-label="' . esc_attr__( 'Remove variation', 'drgr-seo' ) . '">×</button>';
        echo '</div>';
    }
    echo '</div>';
    printf(
        '<button type="button" class="button drgr-btn-add-var" data-list="%s" data-field-name="%s" data-radio-name="%s" data-is-textarea="%s">%s</button>',
        esc_attr( $list_id ),
        esc_attr( $field_name ),
        esc_attr( $radio_name ),
        $is_textarea ? '1' : '0',
        esc_html__( '+ Add Variation', 'drgr-seo' )
    );
}
?>

<div class="drgr-meta-box">
    <p class="drgr-vars-hint">
        <?php esc_html_e( 'Available variables:', 'drgr-seo' ); ?>
        <code>%%title%% %%sitename%% %%sep%% %%description%% %%category%% %%date%% %%currentyear%% %%name%%</code>
        &mdash; <?php esc_html_e( 'Leave blank to use global template.', 'drgr-seo' ); ?>
    </p>

    <!-- ══ SEO META ══════════════════════════════════════════════════════ -->
    <div class="drgr-section">
        <h3>🔍 <?php esc_html_e( 'SEO Meta Tags', 'drgr-seo' ); ?></h3>

        <div class="drgr-field">
            <label for="drgr_seo_title"><strong><?php esc_html_e( 'SEO Title', 'drgr-seo' ); ?></strong>
                <span class="drgr-hint"><?php esc_html_e( '(overrides active variation &amp; global template)', 'drgr-seo' ); ?></span>
            </label>
            <input type="text" id="drgr_seo_title" name="drgr_seo_title"
                   value="<?php echo esc_attr( $seo_title ); ?>" class="large-text">
        </div>

        <div class="drgr-field drgr-variations-wrap">
            <label><strong><?php esc_html_e( 'SEO Title Variations', 'drgr-seo' ); ?></strong></label>
            <?php drgr_render_variations( 'drgr-seo-title-vars', 'drgr_seo_title_variations', 'drgr_active_title_var',
                $var_meta['seo_title']['vars'], $var_meta['seo_title']['active'] ); ?>
        </div>

        <div class="drgr-field">
            <label for="drgr_seo_description"><strong><?php esc_html_e( 'SEO Description', 'drgr-seo' ); ?></strong></label>
            <textarea id="drgr_seo_description" name="drgr_seo_description"
                      class="large-text" rows="3"><?php echo esc_textarea( $seo_desc ); ?></textarea>
        </div>

        <div class="drgr-field drgr-variations-wrap">
            <label><strong><?php esc_html_e( 'SEO Description Variations', 'drgr-seo' ); ?></strong></label>
            <?php drgr_render_variations( 'drgr-seo-desc-vars', 'drgr_seo_desc_variations', 'drgr_active_desc_var',
                $var_meta['seo_desc']['vars'], $var_meta['seo_desc']['active'], true ); ?>
        </div>
    </div><!-- /drgr-section SEO -->

    <!-- ══ OPEN GRAPH ════════════════════════════════════════════════════ -->
    <div class="drgr-section">
        <h3>📘 <?php esc_html_e( 'Open Graph (OG) Meta Tags', 'drgr-seo' ); ?></h3>

        <div class="drgr-field">
            <label for="drgr_og_title"><strong><?php esc_html_e( 'OG Title', 'drgr-seo' ); ?></strong></label>
            <input type="text" id="drgr_og_title" name="drgr_og_title"
                   value="<?php echo esc_attr( $og_title ); ?>" class="large-text">
        </div>

        <div class="drgr-field drgr-variations-wrap">
            <label><strong><?php esc_html_e( 'OG Title Variations', 'drgr-seo' ); ?></strong></label>
            <?php drgr_render_variations( 'drgr-og-title-vars', 'drgr_og_title_variations', 'drgr_active_og_title_var',
                $var_meta['og_title']['vars'], $var_meta['og_title']['active'] ); ?>
        </div>

        <div class="drgr-field">
            <label for="drgr_og_description"><strong><?php esc_html_e( 'OG Description', 'drgr-seo' ); ?></strong></label>
            <textarea id="drgr_og_description" name="drgr_og_description"
                      class="large-text" rows="3"><?php echo esc_textarea( $og_desc ); ?></textarea>
        </div>

        <div class="drgr-field drgr-variations-wrap">
            <label><strong><?php esc_html_e( 'OG Description Variations', 'drgr-seo' ); ?></strong></label>
            <?php drgr_render_variations( 'drgr-og-desc-vars', 'drgr_og_desc_variations', 'drgr_active_og_desc_var',
                $var_meta['og_desc']['vars'], $var_meta['og_desc']['active'], true ); ?>
        </div>
    </div><!-- /drgr-section OG -->

    <!-- ══ TWITTER / X ═══════════════════════════════════════════════════ -->
    <div class="drgr-section">
        <h3>𝕏 <?php esc_html_e( 'Twitter / X Meta Tags', 'drgr-seo' ); ?></h3>

        <div class="drgr-field">
            <label for="drgr_tw_title"><strong><?php esc_html_e( 'Twitter Title', 'drgr-seo' ); ?></strong></label>
            <input type="text" id="drgr_tw_title" name="drgr_tw_title"
                   value="<?php echo esc_attr( $tw_title ); ?>" class="large-text">
        </div>

        <div class="drgr-field drgr-variations-wrap">
            <label><strong><?php esc_html_e( 'Twitter Title Variations', 'drgr-seo' ); ?></strong></label>
            <?php drgr_render_variations( 'drgr-tw-title-vars', 'drgr_tw_title_variations', 'drgr_active_tw_title_var',
                $var_meta['tw_title']['vars'], $var_meta['tw_title']['active'] ); ?>
        </div>

        <div class="drgr-field">
            <label for="drgr_tw_description"><strong><?php esc_html_e( 'Twitter Description', 'drgr-seo' ); ?></strong></label>
            <textarea id="drgr_tw_description" name="drgr_tw_description"
                      class="large-text" rows="3"><?php echo esc_textarea( $tw_desc ); ?></textarea>
        </div>

        <div class="drgr-field drgr-variations-wrap">
            <label><strong><?php esc_html_e( 'Twitter Description Variations', 'drgr-seo' ); ?></strong></label>
            <?php drgr_render_variations( 'drgr-tw-desc-vars', 'drgr_tw_desc_variations', 'drgr_active_tw_desc_var',
                $var_meta['tw_desc']['vars'], $var_meta['tw_desc']['active'], true ); ?>
        </div>
    </div><!-- /drgr-section Twitter -->

    <!-- ══ YOAST CONTROL ═════════════════════════════════════════════════ -->
    <div class="drgr-section drgr-section-yoast">
        <h3>⚙️ <?php esc_html_e( 'Yoast Integration', 'drgr-seo' ); ?></h3>
        <label>
            <input type="checkbox" name="drgr_disable_yoast" value="1"
                   <?php checked( $disable_yoast, '1' ); ?>>
            <?php esc_html_e( 'Disable Yoast SEO meta output for this page (DRGR SEO will replace it)', 'drgr-seo' ); ?>
        </label>
    </div>
</div><!-- /drgr-meta-box -->

<script>
(function($) {
    // Add variation row
    $(document).on('click', '.drgr-btn-add-var', function() {
        var listId     = $(this).data('list');
        var fieldName  = $(this).data('field-name');
        var radioName  = $(this).data('radio-name');
        var isTextarea = $(this).data('is-textarea') === 1 || $(this).data('is-textarea') === '1';
        var $list      = $('#' + listId);
        var idx        = $list.find('.drgr-variation-row').length;

        var inputHtml = isTextarea
            ? '<textarea name="' + fieldName + '[]" class="large-text" rows="2"></textarea>'
            : '<input type="text" name="' + fieldName + '[]" class="large-text" value="">';

        $list.append(
            '<div class="drgr-variation-row">' +
            '<input type="radio" name="' + radioName + '" value="' + idx + '" title="<?php esc_attr_e( 'Use this variation', 'drgr-seo' ); ?>">' +
            inputHtml +
            '<button type="button" class="button drgr-btn-rm-var" data-list="' + listId + '" aria-label="<?php esc_attr_e( 'Remove variation', 'drgr-seo' ); ?>">×</button>' +
            '</div>'
        );
    });

    // Remove variation row
    $(document).on('click', '.drgr-btn-rm-var', function() {
        $(this).closest('.drgr-variation-row').remove();
        // Re-index radio values
        var listId = $(this).data('list');
        $('#' + listId).find('.drgr-variation-row').each(function(i) {
            $(this).find('input[type="radio"]').val(i);
        });
    });
})(jQuery);
</script>
