<?php
/**
 * DRGR_Meta_Replacer — resolves Yoast %%variable%% tokens and outputs
 * <title>, <meta name="description">, Open Graph and Twitter/X card tags.
 *
 * Works with or without Yoast SEO installed.
 */

if ( ! defined( 'ABSPATH' ) ) exit;

class DRGR_Meta_Replacer {

    /** Plugin settings array (from DRGR_SEO_Manager::get_settings()). */
    private $settings;

    /**
     * @param array $settings Plugin settings.
     */
    public function __construct( array $settings = array() ) {
        $this->settings = $settings;
    }

    // ─── Public API ──────────────────────────────────────────────────────────

    /**
     * Output all meta tags for the given post to wp_head.
     *
     * @param int $post_id
     */
    public function output_meta_tags( $post_id ) {
        $post = get_post( $post_id );
        if ( ! $post ) return;

        // ── SEO title & description ──────────────────────────────────────────
        $seo_title = $this->resolve( get_post_meta( $post_id, '_drgr_seo_title',       true ), $post );
        $seo_desc  = $this->resolve( get_post_meta( $post_id, '_drgr_seo_description', true ), $post );

        // Fall back to global templates when per-post fields are empty
        if ( $seo_title === '' ) {
            $template  = $this->get_template( $post->post_type, 'title' );
            $seo_title = $this->resolve( $template, $post );
        }
        if ( $seo_desc === '' ) {
            $template = $this->get_template( $post->post_type, 'description' );
            $seo_desc = $this->resolve( $template, $post );
        }

        // ── OG fields ────────────────────────────────────────────────────────
        $og_title = $this->resolve( get_post_meta( $post_id, '_drgr_og_title',       true ), $post );
        $og_desc  = $this->resolve( get_post_meta( $post_id, '_drgr_og_description', true ), $post );

        if ( $og_title === '' ) $og_title = $seo_title;
        if ( $og_desc  === '' ) $og_desc  = $seo_desc;

        // ── Twitter/X fields ─────────────────────────────────────────────────
        $tw_title = $this->resolve( get_post_meta( $post_id, '_drgr_tw_title',       true ), $post );
        $tw_desc  = $this->resolve( get_post_meta( $post_id, '_drgr_tw_description', true ), $post );

        if ( $tw_title === '' ) $tw_title = $og_title;
        if ( $tw_desc  === '' ) $tw_desc  = $og_desc;

        // ── Emit tags ────────────────────────────────────────────────────────
        echo "\n<!-- DRGR SEO -->\n";

        if ( $seo_title !== '' ) {
            echo '<title>' . esc_html( $seo_title ) . "</title>\n";
        }
        if ( $seo_desc !== '' ) {
            echo '<meta name="description" content="' . esc_attr( $seo_desc ) . "\">\n";
        }

        // Open Graph
        $og_type  = 'article';
        $og_url   = get_permalink( $post_id );
        $og_image = $this->get_og_image( $post_id );

        echo '<meta property="og:type"  content="' . esc_attr( $og_type ) . "\">\n";
        echo '<meta property="og:url"   content="' . esc_attr( $og_url ) . "\">\n";
        if ( $og_title !== '' ) {
            echo '<meta property="og:title"       content="' . esc_attr( $og_title ) . "\">\n";
        }
        if ( $og_desc !== '' ) {
            echo '<meta property="og:description" content="' . esc_attr( $og_desc ) . "\">\n";
        }
        if ( $og_image ) {
            echo '<meta property="og:image" content="' . esc_attr( $og_image ) . "\">\n";
        }

        // Twitter / X card
        echo '<meta name="twitter:card" content="summary_large_image">' . "\n";
        if ( $tw_title !== '' ) {
            echo '<meta name="twitter:title"       content="' . esc_attr( $tw_title ) . "\">\n";
        }
        if ( $tw_desc !== '' ) {
            echo '<meta name="twitter:description" content="' . esc_attr( $tw_desc ) . "\">\n";
        }
        if ( $og_image ) {
            echo '<meta name="twitter:image" content="' . esc_attr( $og_image ) . "\">\n";
        }

        echo "<!-- /DRGR SEO -->\n\n";
    }

    // ─── Token resolution ────────────────────────────────────────────────────

    /**
     * Replace %%variable%% tokens in $template for $post.
     *
     * Uses WPSEO_Replace_Vars when Yoast is active, otherwise falls back to
     * a built-in minimal resolver.
     *
     * @param  string   $template
     * @param  WP_Post  $post
     * @return string   Resolved string (trimmed).
     */
    public function resolve( $template, WP_Post $post ) {
        $template = (string) $template;
        if ( $template === '' ) return '';

        if ( class_exists( 'WPSEO_Replace_Vars' ) ) {
            return trim( WPSEO_Replace_Vars::get_instance()->replace( $template, $post ) );
        }

        return trim( $this->builtin_replace( $template, $post ) );
    }

    /**
     * Minimal %%variable%% resolver used when Yoast is NOT active.
     *
     * Supported tokens: %%title%%, %%excerpt%%, %%sitename%%, %%sep%%,
     * %%post_type%%, %%currentyear%%, %%id%%, %%author%%,
     * %%date%%, %%modified%%, %%tag%%, %%category%%.
     *
     * @param  string   $template
     * @param  WP_Post  $post
     * @return string
     */
    private function builtin_replace( $template, WP_Post $post ) {
        $sep = apply_filters( 'wpseo_replacementvar_sep', '-' );

        $category = '';
        $terms    = get_the_terms( $post->ID, 'category' );
        if ( is_array( $terms ) && $terms ) {
            $category = $terms[0]->name;
        }

        $tag   = '';
        $ttags = get_the_terms( $post->ID, 'post_tag' );
        if ( is_array( $ttags ) && $ttags ) {
            $tag = $ttags[0]->name;
        }

        $map = array(
            '%%title%%'       => get_the_title( $post->ID ),
            '%%excerpt%%'     => wp_strip_all_tags( get_the_excerpt( $post ) ),
            '%%sitename%%'    => get_bloginfo( 'name' ),
            '%%sitedesc%%'    => get_bloginfo( 'description' ),
            '%%sep%%'         => $sep,
            '%%post_type%%'   => $post->post_type,
            '%%currentyear%%' => gmdate( 'Y' ),
            '%%id%%'          => (string) $post->ID,
            '%%author%%'      => get_the_author_meta( 'display_name', (int) $post->post_author ),
            '%%date%%'        => get_the_date( '', $post ),
            '%%modified%%'    => get_the_modified_date( '', $post ),
            '%%tag%%'         => $tag,
            '%%category%%'    => $category,
        );

        return str_replace( array_keys( $map ), array_values( $map ), $template );
    }

    // ─── Helpers ─────────────────────────────────────────────────────────────

    /**
     * Get the per-post-type template from settings.
     *
     * @param  string $post_type
     * @param  string $field  'title' or 'description'
     * @return string
     */
    private function get_template( $post_type, $field ) {
        $templates = isset( $this->settings['templates'] ) ? $this->settings['templates'] : array();
        $key       = $post_type . '_' . $field;
        return isset( $templates[ $key ] ) ? (string) $templates[ $key ] : '';
    }

    /**
     * Retrieve a suitable OG image URL for the post.
     *
     * Priority: custom _drgr_og_image meta → featured image → first attached image.
     *
     * @param  int $post_id
     * @return string|null
     */
    private function get_og_image( $post_id ) {
        $custom = get_post_meta( $post_id, '_drgr_og_image', true );
        if ( $custom ) return esc_url_raw( $custom );

        if ( has_post_thumbnail( $post_id ) ) {
            $src = wp_get_attachment_image_src( get_post_thumbnail_id( $post_id ), 'large' );
            if ( $src ) return $src[0];
        }

        // First attached image
        $attachments = get_posts( array(
            'post_type'      => 'attachment',
            'post_mime_type' => 'image',
            'post_parent'    => $post_id,
            'numberposts'    => 1,
            'fields'         => 'ids',
        ) );
        if ( $attachments ) {
            $src = wp_get_attachment_image_src( $attachments[0], 'large' );
            if ( $src ) return $src[0];
        }

        return null;
    }
}
